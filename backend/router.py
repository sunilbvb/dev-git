import os
import json
import time
import subprocess
import threading
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, Optional, List
import re
import shutil

_JOBS = {}
_JOBS_LOCK = threading.Lock()
_NEXT_JOB_ID = 1
_MAX_LOG_CHARS = 40000
_GIT_LAST_FETCH = {}
_GIT_AUTH_TOKEN = ""
_OLLAMA_BASE_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434').rstrip('/')
_OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'llama3')
_AI_MAX_DIFF_CHARS = int(os.environ.get('AI_MAX_DIFF_CHARS', '120000'))
_WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()

def set_workspace_root(path: Any) -> None:
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path).expanduser().resolve()

def get_workspace_root() -> Path:
    return _WORKSPACE_ROOT

def handle_workspace_switch(data: dict) -> dict:
    new_path_str = (data.get("workspace") or data.get("workspacePath") or data.get("path") or "").strip()
    if not new_path_str:
        return {"success": False, "error": "Missing workspace path"}

    new_path = Path(new_path_str).expanduser().resolve()
    if not new_path.exists() or not new_path.is_dir():
        return {"success": False, "error": f"Directory does not exist: {new_path}"}

    set_workspace_root(new_path)
    if _CACHE_FILE.exists():
        try:
            _CACHE_FILE.unlink()
        except Exception:
            pass

    return {
        "success": True,
        "message": f"Workspace switched to {new_path}",
        "workspaceRoot": str(new_path),
        "name": new_path.name
    }

_CACHE_FILE = Path(__file__).resolve().parent / "git_repos_cache.json"

def _discover_git_repos(workspace_root: Path) -> list[Path]:
    root = workspace_root.resolve()
    repos: set[Path] = set()

    if (root / ".git").is_dir() or (root / ".git").is_file():
        repos.add(root)

    custom_scan_dirs = []
    custom_excludes = set()

    config_file = root / ".devgit.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                for inc in cfg.get("include") or []:
                    p = (root / inc).resolve()
                    if p.exists():
                        custom_scan_dirs.append(p)
                groups = cfg.get("groups") or {}
                if isinstance(groups, dict):
                    for _, group_dirs in groups.items():
                        for g in group_dirs:
                            p = (root / g).resolve()
                            if p.exists():
                                custom_scan_dirs.append(p)
                for exc in cfg.get("exclude") or []:
                    custom_excludes.add(exc)
        except Exception as e:
            print(f"[DevGit] Warning reading .devgit.json: {e}")

    preferred_roots = custom_scan_dirs or [
        root / "apps",
        root / "packages",
        root / "tool",
        root / "tools",
        root / "services",
        root / "libs",
    ]
    scan_roots = [sr for sr in preferred_roots if sr.exists()]
    if not scan_roots and root.exists():
        scan_roots = [root]

    base_excludes = {"build", ".dart_tool", ".idea", ".pub", ".venv", "node_modules", "Pods", "DerivedData"} | custom_excludes
    for sr in scan_roots:
        if (sr / ".git").is_dir() or (sr / ".git").is_file():
            repos.add(sr)
            continue
        for dirpath, dirnames, filenames in os.walk(sr):
            dirnames[:] = [
                d for d in dirnames
                if d not in base_excludes
            ]
            dp = Path(dirpath)
            if (dp / ".git").is_dir() or (dp / ".git").is_file():
                repos.add(dp.resolve())
                dirnames[:] = []
    return sorted(repos, key=lambda p: str(p))

def _new_job_id():
    global _NEXT_JOB_ID
    with _JOBS_LOCK:
        job_id = str(_NEXT_JOB_ID)
        _NEXT_JOB_ID += 1
        return job_id

def _resolve_executable(name: str) -> str:
    import shutil
    path = shutil.which(name)
    if path: return path
    for p in [f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"]:
        if Path(p).exists(): return p
    return ""

def _git_has_staged_changes(repo: Path) -> bool:
    code, out, _ = _run_git(repo, ["diff", "--staged", "--name-only"], timeout=15)
    return code == 0 and bool(out.strip())

def _git_has_unstaged_changes(repo: Path) -> bool:
    code, out, _ = _run_git(repo, ["diff", "--name-only"], timeout=15)
    return code == 0 and bool(out.strip())

def _git_is_dirty(repo: Path) -> bool:
    code, out, _ = _run_git(repo, ["status", "--porcelain"], timeout=15)
    return code == 0 and bool(out.strip())

def _ollama_generate(system: str, prompt: str) -> str:
    model = _resolve_ollama_model()
    url = f"{_OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 160,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(body or "{}")
            return str(obj.get("response") or "").strip()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach Ollama at {url}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama generate failed: {e}") from e

def _run_ollama_cli(args: list[str], timeout_seconds: int = 120) -> dict:
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        for candidate in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama", "/usr/bin/ollama"]:
            if Path(candidate).exists():
                ollama_bin = candidate
                break
    if not ollama_bin:
        raise RuntimeError(
            "Ollama CLI not found. Install Ollama or start dashboard from a shell where `ollama` is in PATH."
        )
    proc = subprocess.run(
        [ollama_bin] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        env=_get_enhanced_env(),
    )
    return {
        "exitCode": proc.returncode,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }

def _strip_ansi_and_spinner_noise(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    cleaned = re.sub(r"[\u2800-\u28FF]", "", cleaned)
    cleaned = re.sub(r"[\r\t]", " ", cleaned)
    lines = []
    for line in cleaned.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        if re.search(r"\b(pulling|downloading|verifying|writing|reading)\b.*\b(layer|manifest|sha256:)\b", line_clean, re.I):
            continue
        if re.match(r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\-\|\/\\]+$", line_clean):
            continue
        lines.append(line)
    return "\n".join(lines).strip()

def _resolve_ollama_model() -> str:
    env_model = os.environ.get("OLLAMA_MODEL")
    if env_model:
        return env_model
    try:
        url = f"{_OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            if "deepseek-r1:latest" in models:
                return "deepseek-r1:latest"
            for m in models:
                if "deepseek-r1" in m:
                    return m
            if models:
                return models[0]
    except Exception:
        pass
    return "deepseek-r1:latest"

def _append_job_log(job_id: str, field: str, chunk: str) -> None:
    if not chunk:
        return
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        if field == "output":
            job["output"] = (job.get("output") or "") + chunk
        elif field == "error":
            job["error"] = (job.get("error") or "") + chunk

def _get_enhanced_env() -> dict:
    env = os.environ.copy()
    home = env.get("HOME")
    extra_paths = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    if home:
        extra_paths.extend([
            f"{home}/.pub-cache/bin",
            f"{home}/development/flutter/bin",
            f"{home}/flutter/bin",
            f"{home}/fvm/default/bin",
            f"{home}/.local/bin",
        ])
    existing = env.get("PATH", "")
    for p in extra_paths:
        if Path(p).exists() and p not in existing:
            existing = f"{p}:{existing}"
    env["PATH"] = existing
    auth_token = _get_git_auth_token()
    if auth_token:
        env["GITHUB_TOKEN"] = auth_token
        env["GH_TOKEN"] = auth_token
    return env

def _set_git_auth_token(token: str):
    global _GIT_AUTH_TOKEN
    _GIT_AUTH_TOKEN = str(token or "").strip()

def _get_git_auth_token() -> str:
    global _GIT_AUTH_TOKEN
    return _GIT_AUTH_TOKEN

def _run_git(repo: Path, args: list[str], timeout: int = 10, token: str = "") -> tuple[int, str, str]:
    cmd = ["git", "-C", str(repo)] + args
    env = _get_enhanced_env()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout.strip(), (proc.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)

def _git_repo_status(repo: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    code, head_out, _ = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
    current_head = head_out.strip() if code == 0 else ""
    status_branch = (branch or current_head).strip()

    upstream = ""
    if status_branch:
        code, upstream_out, _ = _run_git(
            repo,
            ["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{status_branch}"],
            timeout=10,
        )
        upstream = upstream_out.strip() if code == 0 else ""

    ahead = 0
    behind = 0
    if status_branch and upstream:
        code, counts_out, _ = _run_git(
            repo,
            ["rev-list", "--left-right", "--count", f"{status_branch}...{upstream}"],
            timeout=20,
        )
        if code == 0:
            parts = counts_out.split()
            if len(parts) >= 2:
                ahead = int(parts[0]) if parts[0].isdigit() else 0
                behind = int(parts[1]) if parts[1].isdigit() else 0

    code, status_out, _ = _run_git(repo, ["status", "--porcelain"], timeout=15)
    status_lines = [line for line in status_out.splitlines() if line.strip()] if code == 0 else []
    conflict = any(line[:2] in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"} for line in status_lines)

    return {
        "name": repo.name,
        "path": str(repo),
        "branch": status_branch,
        "dirty": bool(status_lines) if not branch or branch == current_head else False,
        "changes": len(status_lines) if not branch or branch == current_head else 0,
        "ahead": ahead,
        "behind": behind,
        "hasUpstream": bool(upstream),
        "upstream": upstream,
        "conflict": conflict if not branch or branch == current_head else False,
    }

def _get_melos_app_name(repo_path: Path) -> str:
    path_str = str(repo_path.resolve())
    if path_str == str(_WORKSPACE_ROOT.resolve()):
        return "all"
    try:
        rel = repo_path.resolve().relative_to(_WORKSPACE_ROOT.resolve())
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "apps":
            return parts[1]
    except Exception:
        pass
    if "apps" in repo_path.parts:
        idx = repo_path.parts.index("apps")
        if idx + 1 < len(repo_path.parts):
            return repo_path.parts[idx + 1]
    return repo_path.name

def _get_melos_scope_name(app_name: str) -> str:
    if not app_name or app_name == "all":
        return app_name or ""
    # Try reading pubspec.yaml for the real package name
    app_dir = _WORKSPACE_ROOT / "apps" / app_name
    pubspec = app_dir / "pubspec.yaml"
    if pubspec.exists():
        try:
            for line in pubspec.read_text(encoding="utf-8").splitlines():
                if line.startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
        except Exception:
            pass
    return app_name.lower().replace("-", "_")

def _translate_branch_name(branch_name: str, app_name: str, is_app_repo: bool) -> str:
    if not app_name or app_name == "all":
        return branch_name
    if branch_name.lower() in ["develop", "main", "master", "head"]:
        return branch_name
    app_prefix = app_name.lower().replace("_", "-") + "-"
    clean_app = app_prefix.rstrip("-")
    parts = branch_name.split("/")
    if len(parts) > 1:
        has_app_segment = (parts[1] == clean_app)
        has_app_dash_prefix = parts[1].startswith(app_prefix)
        if is_app_repo:
            if has_app_segment:
                parts.pop(1)
            elif has_app_dash_prefix:
                parts[1] = parts[1][len(app_prefix):]
        else:
            if not has_app_segment and not has_app_dash_prefix:
                parts.insert(1, clean_app)
            elif has_app_dash_prefix:
                v_scope = parts[1][len(app_prefix):]
                parts[1] = clean_app
                parts.insert(2, v_scope)
        return "/".join(parts)
    return branch_name

def _resolve_melos_cwd() -> Path:
    if (_WORKSPACE_ROOT / "apps").exists() or (_WORKSPACE_ROOT / "packages").exists():
        return _WORKSPACE_ROOT
    return _WORKSPACE_ROOT

def _get_melos_scope_paths(app_name: str) -> list[Path]:
    if not app_name:
        return []
    melos_bin = _resolve_melos_bin()
    scope = _get_melos_scope_name(app_name)
    cwd = _resolve_melos_cwd()
    cmd = [melos_bin, "list", "--include-dependencies", "--json"]
    if scope and scope != "all":
        cmd.append(f"--scope={scope}")
    env = _get_enhanced_env()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15, env=env)
        if proc.returncode == 0:
            import json
            items = json.loads(proc.stdout)
            return [Path(item["location"]).resolve() for item in items]
    except Exception:
        pass
    return []

def _get_repos_in_melos_scope(app_name: str) -> list[Path]:
    melos_bin = _resolve_melos_bin()
    scope = _get_melos_scope_name(app_name)
    cwd = _resolve_melos_cwd()
    
    cmd = [melos_bin, "list", "--parsable"]
    if scope and scope != "all":
        cmd.extend([f"--scope={scope}", "--include-dependencies"])
        
    env = _get_enhanced_env()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=env
        )
        if proc.returncode != 0:
            return _discover_git_repos(_WORKSPACE_ROOT)
            
        package_paths = [Path(line.strip()).resolve() for line in proc.stdout.splitlines() if line.strip()]
        
        discovered_repos = _discover_git_repos(_WORKSPACE_ROOT)
        matched_repos = set()
        
        for pkg_path in package_paths:
            best_repo = None
            for r in discovered_repos:
                try:
                    pkg_path.relative_to(r)
                    if best_repo is None or len(r.parts) > len(best_repo.parts):
                        best_repo = r
                except ValueError:
                    pass
            if best_repo:
                matched_repos.add(best_repo)
                
        if not matched_repos:
            return discovered_repos
            
        return sorted(list(matched_repos))
    except Exception:
        return _discover_git_repos(_WORKSPACE_ROOT)

def _resolve_unique_git_roots(paths: list[Path], discovered_repos: Optional[list[Path]] = None) -> list[Path]:
    discovered = discovered_repos if discovered_repos is not None else _discover_git_repos(_WORKSPACE_ROOT)
    unique_repos: dict[str, Path] = {}

    for path in paths:
        resolved_path = path.resolve()
        git_root = None
        code, out, _ = _run_git(resolved_path, ["rev-parse", "--show-toplevel"], timeout=5)
        if code == 0 and out.strip():
            git_root = Path(out.strip()).resolve()
        else:
            for repo in discovered:
                try:
                    resolved_path.relative_to(repo)
                    if git_root is None or len(repo.parts) > len(git_root.parts):
                        git_root = repo
                except ValueError:
                    pass

        if git_root:
            unique_repos[str(git_root)] = git_root

    return sorted(unique_repos.values(), key=lambda p: str(p))

def _get_melos_release_repos(app_name: str, target: Path) -> tuple[list[Path], str]:
    if not app_name:
        return [target], ""

    scope_paths = _get_melos_scope_paths(app_name)
    if not scope_paths:
        return [], (
            f"Melos scope could not be resolved for '{app_name}'. "
            "No release tags were created. Check that melos is installed and melos.yaml includes this app."
        )

    if target not in scope_paths:
        scope_paths.insert(0, target)

    discovered = _discover_git_repos(_WORKSPACE_ROOT)
    scope_repos = _resolve_unique_git_roots(scope_paths, discovered)
    if not scope_repos:
        return [], f"Melos scope for '{app_name}' did not resolve to any git repositories."

    return scope_repos, ""

def _resolve_melos_bin() -> str:
    melos_bin = _resolve_executable("melos")
    if melos_bin:
        return melos_bin
    home = os.environ.get("HOME")
    if home:
        candidates = [
            f"{home}/.pub-cache/bin/melos",
            "/opt/homebrew/bin/melos",
            "/usr/local/bin/melos"
        ]
        for c in candidates:
            if Path(c).exists():
                return c
    return "melos"

def _ensure_workspace_tool_scripts(workspace_root: Path) -> None:
    """No-op: Standalone mode does not inject scripts into target workspaces."""
    pass

def _update_cache_repo_status(repo_path: str, status: dict):
    if not _CACHE_FILE.exists():
        return
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data or not isinstance(data, dict) or "repos" not in data:
            return
        
        updated = False
        target_path = str(Path(repo_path).resolve())
        for repo in data["repos"]:
            if str(Path(repo.get("path", "")).resolve()) == target_path:
                for k, v in status.items():
                    repo[k] = v
                updated = True
                break
        
        if updated:
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def serve_git_repos(path: str) -> Dict[str, Any]:
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(path).query)
    force_refresh = (query.get("refresh") or ["false"])[0].lower() == "true"

    if not force_refresh and _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if cached_data and isinstance(cached_data, dict) and cached_data.get("success"):
                    return cached_data
        except Exception:
            pass

    workspace_root = _WORKSPACE_ROOT
    _ensure_workspace_tool_scripts(workspace_root)
    repos = _discover_git_repos(workspace_root)
    payload = []
    for repo in repos:
        payload.append(_git_repo_status(repo))
    
    response = {"success": True, "repos": payload}
    
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Gitflow Cache] Failed to write cache file: {e}")
        try:
            with open("/tmp/git_cache_err.log", "a") as err_f:
                err_f.write(f"Write error: {str(e)}\n")
        except Exception:
            pass

    return response

def serve_git_user(path: str) -> Dict[str, Any]:
        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        author_name = ""
        author_email = ""
        if repos:
            code, out, _ = _run_git(repos[0], ["config", "user.name"])
            if code == 0:
                author_name = out.strip()
            code, out, _ = _run_git(repos[0], ["config", "user.email"])
            if code == 0:
                author_email = out.strip()
        return {"success": True, "name": author_name, "email": author_email}

def serve_git_branches(path: str) -> Dict[str, Any]:
        from urllib.parse import urlparse, parse_qs

        workspace_root = _WORKSPACE_ROOT
        _ensure_workspace_tool_scripts(workspace_root)
        query = parse_qs(urlparse(path).query)
        repo_path = (query.get("repoPath") or [""])[0]
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
        repo = Path(repo_path).resolve()
        repos = _discover_git_repos(workspace_root)
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}

        quick = (query.get("quick") or ["false"])[0] == "true"

        code, head, _ = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
        head = head if code == 0 else ""

        # Get branch modification timestamps
        code, out_ts, _ = _run_git(repo, ["for-each-ref", "--format=%(refname:short)|%(committerdate:unix)", "refs/heads", "refs/remotes"], timeout=15)
        branch_timestamps = {}
        if code == 0 and out_ts:
            for line in out_ts.splitlines():
                parts = line.strip().split('|')
                if len(parts) == 2:
                    try:
                        branch_timestamps[parts[0]] = int(parts[1])
                    except Exception:
                        pass

        # List local branches only (names).
        code, out, err = _run_git(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads"], timeout=15)
        if code != 0:
            return {"success": False, "error": err or "Failed to list branches"}
        branches = [line.strip() for line in out.splitlines() if line.strip()]
        branches.sort()

        # Compute ahead/behind for each local branch (best effort).
        branch_statuses: list[dict] = []
        for b in branches:
            if quick:
                branch_statuses.append({
                    "name": b,
                    "hasUpstream": False,
                    "upstream": "",
                    "ahead": 0,
                    "behind": 0,
                    "isMerged": b == head,
                    "updatedAt": branch_timestamps.get(b, 0)
                })
                continue

            status = _git_repo_status(repo, branch=b)
            
            # Check if this branch is already merged into HEAD (active branch)
            is_merged = False
            if head and b != head:
                code_m, _, _ = _run_git(repo, ["merge-base", "--is-ancestor", b, head])
                if code_m == 0:
                    # Also check if its upstream is merged into HEAD, if it has upstream
                    upstream = status.get("upstream")
                    if upstream:
                        code_um, _, _ = _run_git(repo, ["merge-base", "--is-ancestor", upstream, head])
                        if code_um == 0:
                            is_merged = True
                    else:
                        is_merged = True

            branch_statuses.append(
                {
                    "name": b,
                    "hasUpstream": bool(status.get("hasUpstream")),
                    "upstream": status.get("upstream") or "",
                    "ahead": status.get("ahead"),
                    "behind": status.get("behind"),
                    "isMerged": is_merged,
                    "updatedAt": branch_timestamps.get(b, 0)
                }
            )

        remote_branches: list[str] = []
        if not quick:
            # List remote branches too (origin/* etc), excluding symbolic refs like origin/HEAD.
            code, out, _err = _run_git(repo, ["branch", "-r"], timeout=15)
            if code == 0 and out:
                for line in out.splitlines():
                    val = line.strip().lstrip("*").strip()
                    if not val:
                        continue
                    if "->" in val:
                        continue
                    if val.endswith("/HEAD"):
                        continue
                    remote_branches.append(val)

            # Fallback (some git versions/locales behave differently)
            if not remote_branches:
                code, out, _err = _run_git(repo, ["for-each-ref", "--format=%(refname:short)", "refs/remotes"], timeout=15)
                if code == 0 and out:
                    for line in out.splitlines():
                        val = line.strip()
                        if not val or val.endswith("/HEAD"):
                            continue
                        remote_branches.append(val)

            remote_branches = sorted(set(remote_branches))

            # Add remote-only branches to branch_statuses so they appear as "behind" and can be pulled
            local_branch_set = set(branches)
            for rb in remote_branches:
                if rb.startswith("origin/"):
                    local_name = rb[len("origin/"):]
                    if local_name not in local_branch_set and local_name != "HEAD":
                        is_merged = False
                        if head:
                            code_m, _, _ = _run_git(repo, ["merge-base", "--is-ancestor", rb, head])
                            if code_m == 0:
                                is_merged = True

                        behind_count = 1
                        code, counts, _ = _run_git(repo, ["rev-list", "--left-right", "--count", f"{rb}...HEAD"], timeout=12)
                        if code == 0 and counts:
                            parts = counts.split()
                            if len(parts) >= 1:
                                try:
                                    behind_count = int(parts[0])
                                except Exception:
                                    pass
                        if behind_count > 0:
                            branch_statuses.append({
                                "name": local_name,
                                "hasUpstream": True,
                                "upstream": rb,
                                "ahead": 0,
                                "behind": behind_count,
                                "isMerged": is_merged,
                                "remoteOnly": True,
                                "updatedAt": branch_timestamps.get(rb, 0)
                            })
                            branches.append(local_name)
            
            branches = sorted(set(branches))

        return {
            "success": True,
            "repoPath": str(repo),
            "head": head,
            "branches": branches,
            "branchStatuses": branch_statuses,
            "remoteBranches": remote_branches,
            "quick": quick
        }

def serve_git_commits(path: str) -> Dict[str, Any]:
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(path).query)
    repo_path = (query.get("repoPath") or [""])[0]
    branch = (query.get("branch") or [""])[0]

    if not repo_path or not branch:
        return {"success": False, "error": "Missing repoPath or branch"}

    repo = Path(repo_path).resolve()
    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    if repo not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    # Resolve a GitHub "view commit" URL prefix, if the origin remote points at GitHub.
    web_url_prefix = ""
    code_r, rem_url, _ = _run_git(repo, ["remote", "get-url", "origin"], timeout=10)
    if code_r == 0 and rem_url.strip():
        match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", rem_url.strip())
        if match:
            owner, repo_name = match.groups()
            web_url_prefix = f"https://github.com/{owner}/{repo_name}/commit/"

    # Get last 50 commits. Use a rare record separator so commit subjects can safely
    # contain "|" without corrupting the field split, and append --numstat so each
    # commit's changed-file/insertion/deletion counts come back in the same call.
    # Format per record: \x1e<full sha>|<short sha>|<author>|<email>|<abs date>|<rel date>|<subject>
    code, out, err = _run_git(repo, [
        "log", "-n", "50", branch,
        "--pretty=format:%x1e%H|%h|%an|%ae|%ad|%ar|%s",
        "--date=format:%b %d, %Y %I:%M %p",
        "--numstat",
    ])
    if code != 0:
        return {"success": False, "error": f"Failed to get commits: {err or out}"}

    commits = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        lines = record.split("\n")
        header = lines[0]
        parts = header.split('|', 6)
        if len(parts) < 7:
            continue

        files_changed = 0
        insertions = 0
        deletions = 0
        for stat_line in lines[1:]:
            stat_line = stat_line.strip()
            if not stat_line:
                continue
            stat_parts = stat_line.split('\t')
            if len(stat_parts) < 3:
                continue
            added, removed, _fname = stat_parts[0], stat_parts[1], stat_parts[2]
            files_changed += 1
            if added.isdigit():
                insertions += int(added)
            if removed.isdigit():
                deletions += int(removed)

        full_sha = parts[0]
        commits.append({
            "sha": parts[1],
            "fullSha": full_sha,
            "author": parts[2],
            "authorEmail": parts[3],
            "dateAbsolute": parts[4],
            "date": parts[5],
            "message": parts[6],
            "filesChanged": files_changed,
            "insertions": insertions,
            "deletions": deletions,
            "webUrl": f"{web_url_prefix}{full_sha}" if web_url_prefix else "",
        })

    return {"success": True, "commits": commits}

def serve_git_status(path: str) -> Dict[str, Any]:
        from urllib.parse import urlparse, parse_qs

        workspace_root = _WORKSPACE_ROOT
        query = parse_qs(urlparse(path).query)
        repo_path = (query.get("repoPath") or [""])[0]
        branch = (query.get("branch") or [""])[0]
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return
        repo = Path(repo_path).resolve()
        repos = _discover_git_repos(workspace_root)
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        payload = _git_repo_status(repo, branch=branch or None)
        _update_cache_repo_status(repo_path, payload)
        return {"success": True, "status": payload}

def serve_git_diff(path: str) -> Dict[str, Any]:
        from urllib.parse import urlparse, parse_qs

        workspace_root = _WORKSPACE_ROOT
        query = parse_qs(urlparse(path).query)
        repo_path = (query.get("repoPath") or [""])[0]
        staged_raw = (query.get("staged") or ["true"])[0]
        unstaged_raw = (query.get("unstaged") or ["false"])[0]
        max_chars_raw = (query.get("maxChars") or [str(_AI_MAX_DIFF_CHARS)])[0]

        repo_path = str(repo_path or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return

        repos = _discover_git_repos(workspace_root)
        repo = Path(repo_path).resolve()
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        staged = str(staged_raw).lower() in {"1", "true", "yes"}
        unstaged = str(unstaged_raw).lower() in {"1", "true", "yes"}
        try:
            max_chars = int(max_chars_raw)
        except Exception:
            max_chars = _AI_MAX_DIFF_CHARS

        diffs: list[str] = []
        truncated = False
        if staged:
            code, out, err = _run_git(repo, ["diff", "--staged", "--patch", "--no-color", "-M", "-C"], timeout=20)
            if code != 0:
                return {"success": False, "error": err or "Failed to read staged diff"}
                return
            diffs.append(out)
        if unstaged:
            code, out, err = _run_git(repo, ["diff", "--patch", "--no-color", "-M", "-C"], timeout=20)
            if code != 0:
                return {"success": False, "error": err or "Failed to read unstaged diff"}
                return
            diffs.append(out)

        combined = "\n\n".join([d for d in diffs if d is not None]) if diffs else ""
        combined, truncated = _truncate_text(combined, max_chars)

        if _looks_sensitive(combined):
            return {
                "success": False,
                "sensitive": True,
                "error": "Diff appears to contain sensitive material. Refusing to return it via the dashboard API.",
            }

        return {"success": True, "diff": combined, "truncated": truncated}

def serve_git_changes(path: str) -> Dict[str, Any]:
        from urllib.parse import urlparse, parse_qs

        workspace_root = _WORKSPACE_ROOT
        query = parse_qs(urlparse(path).query)
        repo_path = (query.get("repoPath") or [""])[0]
        repo_path = str(repo_path or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return

        repos = _discover_git_repos(workspace_root)
        repo = Path(repo_path).resolve()
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        code, status_out, _ = _run_git(repo, ["status", "--porcelain"], timeout=12)
        files = []
        if code == 0:
            for line in status_out.splitlines():
                if len(line) >= 4:
                    status_code = line[:2]
                    file_path = line[3:].strip('" ')
                    # parse status_code
                    staged = status_code[0] in ('M', 'A', 'D', 'R', 'C')
                    unstaged = status_code[1] in ('M', 'D') or status_code == '??'
                    files.append({
                        "path": file_path,
                        "staged": staged,
                        "unstaged": unstaged,
                        "untracked": status_code == '??',
                        "status": status_code
                    })

        return {
            "success": True,
            "changes": {
                "dirty": _git_is_dirty(repo),
                "hasStaged": _git_has_staged_changes(repo),
                "hasUnstaged": _git_has_unstaged_changes(repo),
                "files": files,
            },
        }

def handle_git_ai_commit_message_async(data: dict) -> Dict[str, Any]:
        
        repo_path = str(data.get("repoPath") or "").strip()
        staged = bool(data.get("staged", True))
        unstaged = bool(data.get("unstaged", False))

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        repo = Path(repo_path).resolve()
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        diffs: list[str] = []
        selected_files = data.get("selectedFiles")
        if isinstance(selected_files, list) and len(selected_files) > 0:
            if staged:
                code, out, err = _run_git(repo, ["diff", "--staged", "--patch", "--no-color", "-M", "-C", "--"] + selected_files, timeout=22)
                if code == 0:
                    diffs.append(out)
            if unstaged:
                code, out, err = _run_git(repo, ["diff", "--patch", "--no-color", "-M", "-C", "--"] + selected_files, timeout=22)
                if code == 0:
                    diffs.append(out)
        else:
            if staged:
                code, out, err = _run_git(repo, ["diff", "--staged", "--patch", "--no-color", "-M", "-C"], timeout=22)
                if code != 0:
                    return {"success": False, "error": err or "Failed to read staged diff"}
                diffs.append(out)
            if unstaged:
                code, out, err = _run_git(repo, ["diff", "--patch", "--no-color", "-M", "-C"], timeout=22)
                if code != 0:
                    return {"success": False, "error": err or "Failed to read unstaged diff"}
                diffs.append(out)

        combined = "\n\n".join([d for d in diffs if d]) if diffs else ""
        combined, truncated = _truncate_text(combined, _AI_MAX_DIFF_CHARS)

        if not combined.strip():
            has_staged = _git_has_staged_changes(repo)
            has_unstaged = _git_has_unstaged_changes(repo)
            is_dirty = _git_is_dirty(repo)
            hint_parts: list[str] = []
            if staged and not has_staged:
                hint_parts.append("Nothing is staged")
            if unstaged and not has_unstaged:
                hint_parts.append("Nothing is unstaged")
            if not hint_parts and not is_dirty:
                hint_parts.append("Working tree is clean")
            hint = ". ".join(hint_parts) if hint_parts else "No changes found for requested scope"
            return {
                "success": False,
                "error": "No diff found for the requested scope.",
                "details": {
                    "dirty": is_dirty,
                    "hasStaged": has_staged,
                    "hasUnstaged": has_unstaged,
                    "requested": {"staged": staged, "unstaged": unstaged},
                    "hint": hint,
                },
            }
            return

        if _looks_sensitive(combined):
            return {"success": False, "sensitive": True, "error": "Diff appears sensitive; refusing AI generation."}
            return

        system = _conventional_commit_system_prompt()
        prompt = _build_commit_prompt(repo, combined, staged=staged, unstaged=unstaged)
        job_id = _new_job_id()
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "id": job_id,
                "type": "git_ai_commit_message",
                "status": "running",
                "startedAt": time.time(),
                "command": "ollama generate",
                "output": "",
                "error": "",
                "repoPath": str(repo),
                "result": None,
                "meta": {"truncatedDiff": truncated},
            }

        def _run_ai_job() -> None:
            try:
                _append_job_log(job_id, "output", "Generating commit message…\n")
                message = _ollama_generate(system=system, prompt=prompt)
                if not message:
                    raise RuntimeError("Model returned empty commit message.")
                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["result"] = {
                            "message": message.strip(),
                            "model": _resolve_ollama_model(),
                        }
                        job["status"] = "success"
                        job["endedAt"] = time.time()
            except Exception as e:
                _append_job_log(job_id, "error", f"\nERROR: {e}\n")
                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["status"] = "error"
                        job["endedAt"] = time.time()

        threading.Thread(target=_run_ai_job, daemon=True).start()
        return {"success": True, "jobId": job_id}

def handle_git_commit_async(data: dict) -> Dict[str, Any]:
        
        repo_path = str(data.get("repoPath") or "").strip()
        message = str(data.get("message") or "").strip()
        push = bool(data.get("push", False))
        stage_all = bool(data.get("stageAll", False))
        remote = str(data.get("remote") or "origin").strip() or "origin"
        branch = str(data.get("branch") or "").strip()

        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return
        if not message:
            return {"success": False, "error": "Missing commit message"}
            return

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        repo = Path(repo_path).resolve()
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        job_id = _new_job_id()
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "id": job_id,
                "type": "git_commit",
                "status": "running",
                "startedAt": time.time(),
                "command": "git commit/push",
                "output": "",
                "error": "",
                "repoPath": str(repo),
            }

        def _run_commit_job() -> None:
            try:
                _append_job_log(job_id, "output", f"==> Repo: {repo}\n")

                selected_files = data.get("selectedFiles")
                if isinstance(selected_files, list) and len(selected_files) > 0:
                    _append_job_log(job_id, "output", "Preparing selective staging by resetting current index…\n")
                    _run_git(repo, ["reset"])
                    _append_job_log(job_id, "output", f"Staging {len(selected_files)} selected files…\n")
                    code, out, err = _run_git(repo, ["add", "--"] + selected_files, timeout=60)
                    if code != 0:
                        raise RuntimeError(err or out or "Failed to stage selected files")
                elif stage_all:
                    _append_job_log(job_id, "output", "Staging all changes (git add -A)…\n")
                    code, out, err = _run_git(repo, ["add", "-A"], timeout=60)
                    if code != 0:
                        raise RuntimeError(err or out or "git add failed")

                _append_job_log(job_id, "output", "Checking staged changes…\n")
                code, staged_out, err = _run_git(repo, ["diff", "--staged", "--name-only"], timeout=20)
                if code != 0:
                    raise RuntimeError(err or "Failed to check staged changes")
                if not staged_out.strip():
                    raise RuntimeError("No staged changes to commit. Stage changes first (or enable 'Stage all').")

                _append_job_log(job_id, "output", "Committing…\n")
                code, out, err = _run_git(repo, ["commit", "-m", message], timeout=120)
                if code != 0:
                    raise RuntimeError(err or out or "git commit failed")
                if out:
                    _append_job_log(job_id, "output", out + "\n")

                if push:
                    resolved_branch = branch
                    if not resolved_branch:
                        code, cur, _ = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=20)
                        resolved_branch = cur if code == 0 else ""
                    if not resolved_branch:
                        raise RuntimeError("Failed to resolve branch for push")

                    _append_job_log(job_id, "output", f"Pushing to {remote} {resolved_branch}…\n")
                    code, pout, perr = _run_git(repo, ["push", remote, resolved_branch], timeout=240)
                    if code != 0:
                        raise RuntimeError(perr or pout or "git push failed")
                    if pout:
                        _append_job_log(job_id, "output", pout + "\n")

                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["status"] = "success"
                        job["endedAt"] = time.time()
            except Exception as e:
                _append_job_log(job_id, "error", f"\nERROR: {e}\n")
                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["status"] = "error"
                        job["endedAt"] = time.time()

        threading.Thread(target=_run_commit_job, daemon=True).start()
        return {"success": True, "jobId": job_id}

def handle_git_terminal_run(data: dict) -> Dict[str, Any]:
        
        repo_path = str(data.get("repoPath") or "").strip()
        cmd_str = str(data.get("command") or "").strip()

        if not repo_path or not cmd_str:
            return {"success": False, "error": "Missing repoPath or command"}
            return

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        repo = Path(repo_path).resolve()
        if repo not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        import shlex
        try:
            args = shlex.split(cmd_str)
        except Exception as e:
            return {"success": False, "error": f"Parse error: {e}"}
            return

        if not args:
            return {"success": False, "error": "Empty command"}
            return

        if args[0] == "git":
            args = args[1:]

        job_id = _new_job_id()
        self._start_git_terminal_job(job_id, repo, args)
        return {"success": True, "jobId": job_id}

def handle_git_fetch(data: dict) -> Dict[str, Any]:

        scope = str(data.get("scope") or "all").strip().lower()  # all | one
        repo_path = str(data.get("repoPath") or "").strip()

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)

        selected: list[Path] = []
        if scope == "one":
            if not repo_path:
                return {"success": False, "error": "Missing repoPath"}
                return
            target = Path(repo_path).resolve()
            if target not in repos:
                return {"success": False, "error": "Unknown repoPath"}
                return
            selected = [target]
        else:
            selected = repos

        job_id = _new_job_id()
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "id": job_id,
                "type": "git_fetch",
                "status": "running",
                "startedAt": time.time(),
                "command": "git fetch",
                "output": "",
                "error": "",
            }

        def _run_fetch():
            try:
                for repo in selected:
                    _append_job_log(job_id, "output", f"\n==> {repo}\n")
                    cmd = ["git", "-C", str(repo), "fetch", "--all", "--prune"]
                    proc = subprocess.Popen(
                        cmd,
                        cwd=str(workspace_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    out, err = proc.communicate()
                    if out:
                        _append_job_log(job_id, "output", out)
                    if err:
                        _append_job_log(job_id, "error", err)
                    if proc.returncode != 0:
                        raise RuntimeError(f"git fetch failed for {repo} (exit {proc.returncode})")
                    _GIT_LAST_FETCH[str(repo)] = time.time()

                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["status"] = "success"
                        job["endedAt"] = time.time()
            except Exception as e:
                _append_job_log(job_id, "error", f"\nERROR: {e}\n")
                with _JOBS_LOCK:
                    job = _JOBS.get(job_id)
                    if job:
                        job["status"] = "error"
                        job["endedAt"] = time.time()

        threading.Thread(target=_run_fetch, daemon=True).start()
        return {"success": True, "jobId": job_id}

def handle_git_pull(data: dict) -> Dict[str, Any]:
        _set_git_auth_token(str(data.get("githubToken") or "").strip())
        repo_path = str(data.get("repoPath") or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}

        use_melos = data.get("useMelos") is True
        app_name = _get_melos_app_name(target) if use_melos else ""

        def _pull_one_repo(r: Path) -> tuple[bool, str]:
            # Get current active branch
            code_b, branch, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "HEAD"])
            if code_b != 0 or not branch:
                return False, "Failed to resolve current branch"
            
            # Check dirty
            code_dirty, status_out, _ = _run_git(r, ["status", "--porcelain"])
            if code_dirty != 0:
                return False, "Failed to check status"
            if status_out.strip():
                return False, "Working tree has uncommitted changes. Please commit or stash them first."
                
            # Fetch
            code_f, _, err_f = _run_git(r, ["fetch", "origin"])
            if code_f != 0:
                return False, f"Fetch failed: {err_f}"
                
            # Check upstream
            code_up, upstream, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
            if code_up != 0 or not upstream:
                # If no upstream, try pulling active branch directly
                code_p, out_p, err_p = _run_git(r, ["pull", "origin", branch])
                if code_p != 0:
                    return False, f"Pull failed: {err_p or out_p}"
                return True, ""
                
            # Fast-forward check
            code_anc, _, _ = _run_git(r, ["merge-base", "--is-ancestor", "HEAD", "@{u}"])
            if code_anc == 0:
                code_ff, out_ff, err_ff = _run_git(r, ["merge", "--ff-only", "@{u}"])
                if code_ff != 0:
                    return False, f"Fast-forward merge failed: {err_ff or out_ff}"
                return True, ""
                
            # Merge diverged
            code_mg, out_mg, err_mg = _run_git(r, ["merge", "--no-commit", "--no-ff", "@{u}"])
            if code_mg != 0:
                _run_git(r, ["merge", "--abort"])
                return False, f"Merge conflict: {err_mg or out_mg}"
            
            # Commit merge
            _run_git(r, ["commit", "--no-edit"])
            return True, ""

        if app_name:
            scope_repos = _get_repos_in_melos_scope(app_name)
            failed_repos = []
            success_count = 0
            for r in scope_repos:
                ok, err_msg = _pull_one_repo(r)
                if not ok:
                    # Ignore repositories where branch doesn't exist on remote/origin or has no upstream
                    if "no upstream branch configured" in err_msg.lower() or "pull failed" in err_msg.lower():
                        continue
                    failed_repos.append(f"{r.name}: {err_msg}")
                else:
                    success_count += 1
            if failed_repos:
                return {"success": False, "error": f"Pull failed on some repositories:\n" + "\n".join(failed_repos)}
            return {"success": True, "message": f"Successfully pulled updates across {success_count} repositories."}

        # Single repo pull
        ok, err_msg = _pull_one_repo(target)
        if not ok:
            return {"success": False, "error": err_msg}
        return {"success": True, "message": "Updated successfully."}

def handle_git_push(data: dict) -> Dict[str, Any]:
        _set_git_auth_token(str(data.get("githubToken") or "").strip())
        repo_path = str(data.get("repoPath") or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}

        use_melos = data.get("useMelos") is True
        app_name = _get_melos_app_name(target) if use_melos else ""
        if app_name:
            scope_repos = _get_repos_in_melos_scope(app_name)
            failed_repos = []
            success_count = 0
            for r in scope_repos:
                code_b, branch_name, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "HEAD"])
                if code_b != 0 or not branch_name:
                    continue
                code_p, out_p, err_p = _run_git(r, ["push", "origin", branch_name])
                if code_p != 0:
                    failed_repos.append(f"{r.name}: {err_p or out_p}")
                else:
                    success_count += 1
            if failed_repos:
                return {"success": False, "error": f"Push failed on some repositories:\n" + "\n".join(failed_repos)}
            return {"success": True, "message": f"Successfully pushed updates across {success_count} repositories."}

        # Resolve branch + upstream (requires upstream for push).
        code, branch, _ = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0 or not branch:
            return {"success": False, "error": "Failed to resolve current branch"}
            return

        code, upstream, _ = _run_git(target, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        if code != 0 or not upstream:
            return {"success": False, "error": "No upstream branch configured for this branch"}
            return

        # Fetch first to detect behind/diverged states.
        code, _out, err = _run_git(target, ["fetch", "--prune", "origin"])
        if code != 0:
            return {"success": False, "error": f"Fetch failed: {err}"}
            return

        # Compute ahead/behind for safety.
        code, counts, _ = _run_git(target, ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"])
        if code != 0 or not counts.strip():
            return {"success": False, "error": "Failed to compute ahead/behind"}
            return
        left_right = counts.strip().split()
        ahead = int(left_right[0]) if len(left_right) > 0 else 0
        behind = int(left_right[1]) if len(left_right) > 1 else 0

        if behind > 0:
            return {
                "success": False,
                "error": f"Branch is behind upstream by {behind} commit(s). Pull first, then push.",
                "ahead": ahead,
                "behind": behind,
            }

        if ahead <= 0:
            return {"success": True, "message": "Nothing to push (already up-to-date)", "ahead": ahead, "behind": behind}
            return

        code, out, err = _run_git(target, ["push"])
        if code == 0:
            return {"success": True, "message": "Pushed successfully", "stdout": out, "ahead": 0, "behind": 0}
        else:
            return {"success": False, "error": err or out or "git push failed"}

def handle_git_stash_pull_pop(data: dict) -> Dict[str, Any]:
        
        repo_path = str(data.get("repoPath") or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        self._run_stash_pull_pop_workflow(target)

def handle_git_sync_all_branches(data: dict) -> Dict[str, Any]:

        repo_path = str(data.get("repoPath") or "").strip()
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
            return

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        # 1. Get current branch
        code, current_branch, _ = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
        current_branch = current_branch if code == 0 else ""

        # 2. Get local branches and their status
        code, out, _ = _run_git(target, ["for-each-ref", "--format=%(refname:short)", "refs/heads"])
        if code != 0:
            return {"success": False, "error": "Failed to list branches"}
            return
        
        branches = [line.strip() for line in out.splitlines() if line.strip()]
        
        synced = []
        errors = []
        
        for b in branches:
            status = _git_repo_status(target, branch=b)
            if status.get("hasUpstream") and status.get("behind", 0) > 0 and status.get("ahead", 0) == 0:
                upstream = status.get("upstream")
                if not upstream:
                    continue
                # If it's safe to fast-forward
                if b == current_branch:
                    # Sync current branch safely
                    code, cout, cerr = _run_git(target, ["merge", "--ff-only", upstream])
                    if code == 0:
                        synced.append(b)
                    else:
                        errors.append(f"Failed to sync {b}: {cerr or cout}")
                else:
                    # Sync non-current branch using fetch
                    parts = upstream.split('/', 1)
                    if len(parts) == 2:
                        remote = parts[0]
                        remote_ref = parts[1]
                        code, cout, cerr = _run_git(target, ["fetch", remote, f"{remote_ref}:{b}"])
                        if code == 0:
                            synced.append(b)
                        else:
                            errors.append(f"Failed to sync {b}: {cerr or cout}")
        
        if errors and not synced:
            return {"success": False, "error": "; ".join(errors)}
        else:
            msg = f"Synchronized {len(synced)} branch(es)."
            if errors:
                msg += f" Encountered {len(errors)} error(s)."
            return {"success": True, "message": msg, "synced": synced, "errors": errors}

def _run_bash_script(repo_path: Path, script_path: Path, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    cmd = ["bash", str(script_path)] + args
    env = _get_enhanced_env()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout.strip(), (proc.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)

def handle_git_branch_action(data: dict) -> Dict[str, Any]:
        _set_git_auth_token(str(data.get("githubToken") or "").strip())
        repo_path = str(data.get("repoPath") or "").strip()
        branch = str(data.get("branch") or "").strip()
        action = str(data.get("action") or "").strip()
        
        if not repo_path or not branch or not action:
            return {"success": False, "error": "Missing parameters"}
            return

        workspace_root = _WORKSPACE_ROOT
        repos = _discover_git_repos(workspace_root)
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}
            return

        # 1. Check if dirty
        code, status_out, _ = _run_git(target, ["status", "--porcelain"])
        if code != 0:
            return {"success": False, "error": "Failed to check git status"}
            return
        if status_out.strip():
            return {"success": False, "dirty": True, "error": "Working tree has uncommitted changes. Please commit or stash them first."}
            return

        # 2. Get current branch
        code, current_branch, _ = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
        if code != 0 or not current_branch:
            return {"success": False, "error": "Failed to resolve current branch"}
            return

        # Helper function to switch back safely
        def _switch_back():
            _run_git(target, ["checkout", current_branch])

        # 3. Perform actions
        if action == "pull":
            use_melos = data.get("useMelos") is True
            app_name = _get_melos_app_name(target) if use_melos else ""

            def _pull_branch_on_repo(r: Path) -> tuple[bool, str]:
                code_l, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{branch}"])
                code_rem, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{branch}"])
                if code_l != 0 and code_rem != 0:
                    return True, ""  # skip silently

                code_dirty, status_out, _ = _run_git(r, ["status", "--porcelain"])
                if code_dirty == 0 and status_out.strip():
                    return False, "Working tree has uncommitted changes"

                code_h, orig, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "HEAD"])
                orig_branch = orig.strip() if code_h == 0 else ""

                code_co, _, co_err = _run_git(r, ["checkout", branch])
                if code_co != 0:
                    return False, f"Failed to checkout {branch}: {co_err}"

                code_p, out_p, err_p = _run_git(r, ["pull", "origin", branch])
                conflict = False
                if code_p != 0:
                    conflict = "conflict" in (err_p or out_p).lower()
                    if conflict:
                        _run_git(r, ["merge", "--abort"])

                if orig_branch and orig_branch != branch:
                    _run_git(r, ["checkout", orig_branch])

                if code_p != 0:
                    return False, f"{'Merge conflict' if conflict else 'Pull failed'}: {err_p or out_p}"
                return True, ""

            if app_name:
                scope_repos = _get_repos_in_melos_scope(app_name)
                failed_repos = []
                success_count = 0
                for r in scope_repos:
                    ok, err_msg = _pull_branch_on_repo(r)
                    if not ok:
                        failed_repos.append(f"{r.name}: {err_msg}")
                    else:
                        success_count += 1
                if failed_repos:
                    return {"success": False, "error": f"Pull failed on some repositories:\n" + "\n".join(failed_repos)}
                return {"success": True, "message": f"Successfully pulled updates for {branch} across {success_count} repositories."}

            # Single repo pull
            ok, err_msg = _pull_branch_on_repo(target)
            if not ok:
                return {"success": False, "error": err_msg}
            return {"success": True, "message": f"Successfully pulled updates for {branch}."}

        elif action == "push":
            use_melos = data.get("useMelos") is True
            app_name = _get_melos_app_name(target) if use_melos else ""

            def _push_branch_on_repo(r: Path) -> tuple[bool, str]:
                code_l, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{branch}"])
                if code_l != 0:
                    return True, ""  # skip silently

                code_p, out_p, err_p = _run_git(r, ["push", "origin", branch])
                if code_p != 0:
                    return False, f"Push failed: {err_p or out_p}"
                return True, ""

            if app_name:
                scope_repos = _get_repos_in_melos_scope(app_name)
                failed_repos = []
                success_count = 0
                for r in scope_repos:
                    ok, err_msg = _push_branch_on_repo(r)
                    if not ok:
                        failed_repos.append(f"{r.name}: {err_msg}")
                    else:
                        success_count += 1
                if failed_repos:
                    return {"success": False, "error": f"Push failed on some repositories:\n" + "\n".join(failed_repos)}
                return {"success": True, "message": f"Successfully pushed {branch} across {success_count} repositories."}

            # Single repo push
            ok, err_msg = _push_branch_on_repo(target)
            if not ok:
                return {"success": False, "error": err_msg}
            return {"success": True, "message": f"Successfully pushed updates for {branch}."}

        elif action == "fetch":
            use_melos = data.get("useMelos") is True
            app_name = _get_melos_app_name(target) if use_melos else ""
            if app_name:
                scope_repos = _get_repos_in_melos_scope(app_name)
                failed_repos = []
                success_count = 0
                for r in scope_repos:
                    code_f, _, err_f = _run_git(r, ["fetch", "origin"])
                    if code_f != 0:
                        failed_repos.append(f"{r.name}: {err_f}")
                    else:
                        success_count += 1
                if failed_repos:
                    return {"success": False, "error": f"Fetch failed on some repositories:\n" + "\n".join(failed_repos)}
                return {"success": True, "message": f"Successfully fetched updates across {success_count} repositories."}

            # Fetch origin is a repository-wide metadata sync and doesn't touch working tree
            code, out, err = _run_git(target, ["fetch", "origin"])
            if code != 0:
                return {"success": False, "error": f"Fetch failed: {err or out}"}
            return {"success": True, "message": f"Successfully fetched updates from origin."}

        elif action == "merge-current-into-this":
            if branch == current_branch:
                return {"success": False, "error": "Cannot merge branch into itself."}
                
            # 1. Checkout target branch
            code, _, err = _run_git(target, ["checkout", branch])
            if code != 0:
                return {"success": False, "error": f"Failed to checkout {branch}: {err}"}
                
            # 2. Merge current branch
            code, out, err = _run_git(target, ["merge", "--no-edit", current_branch])
            if code != 0:
                conflict = "conflict" in (err or out).lower()
                if conflict:
                    _run_git(target, ["merge", "--abort"])
                _switch_back()
                return {"success": False, "conflict": conflict, "error": f"Merge failed: {err or out}"}
                
            # 3. Checkout back
            code, _, err = _run_git(target, ["checkout", current_branch])
            if code != 0:
                return {"success": False, "error": f"Failed to switch back to {current_branch}: {err}"}
                
            return {"success": True, "message": f"Successfully merged {current_branch} into {branch}."}

        elif action == "merge-this-into-current":
            # Merge target branch into current branch
            code, out, err = _run_git(target, ["merge", "--no-edit", branch])
            if code != 0:
                conflict = "conflict" in (err or out).lower()
                if conflict:
                    _run_git(target, ["merge", "--abort"])
                return {"success": False, "conflict": conflict, "error": f"Merge failed: {err or out}"}
                
            return {"success": True, "message": f"Successfully merged {branch} into {current_branch}."}

        elif action == "checkout":
            use_melos = data.get("useMelos") is True
            app_name = _get_melos_app_name(target) if use_melos else ""

            def _branch_exists(r: Path, name: str) -> bool:
                code_l, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{name}"])
                code_r, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{name}"])
                return code_l == 0 or code_r == 0

            def _checkout_one_repo(r: Path, name: str, create_if_missing: Optional[bool]) -> tuple[bool, str]:
                # Check current branch first
                code_head, head_branch, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "HEAD"])
                if code_head == 0 and head_branch.strip() == name:
                    return True, "Already on branch"

                # If branch exists, switch to it
                if _branch_exists(r, name):
                    code_co, _, co_err = _run_git(r, ["checkout", name])
                    if code_co != 0:
                        code_co2, _, co_err2 = _run_git(r, ["checkout", "-b", name, f"origin/{name}"])
                        if code_co2 != 0:
                            return False, f"Failed to checkout {name}: {co_err2 or co_err}"
                    return True, name

                # Branch is missing
                if create_if_missing is True:
                    # Create new local branch pointing to current HEAD
                    code_cb, _, cb_err = _run_git(r, ["checkout", "-b", name])
                    if code_cb != 0:
                        return False, f"Failed to create branch {name}: {cb_err}"
                    return True, name
                elif create_if_missing is False:
                    # Fallback to develop > main > master
                    fallback = None
                    for fb in ["develop", "main", "master"]:
                        if _branch_exists(r, fb):
                            fallback = fb
                            break
                    if fallback:
                        code_co, _, co_err = _run_git(r, ["checkout", fallback])
                        if code_co != 0:
                            return False, f"Failed to checkout fallback {fallback}: {co_err}"
                        return True, fallback
                    return False, f"Branch '{name}' not found, and no fallback branch found"
                else:
                    return False, f"Branch '{name}' does not exist"

            # Check target branch existence across scope
            if app_name:
                scope_repos = _get_repos_in_melos_scope(app_name)
                resolved_branches = {}
                missing_repos = []
                
                for r in scope_repos:
                    is_app_repo = ("/apps/" in str(r.as_posix())) or (r == target)
                    r_branch = _translate_branch_name(branch, app_name, is_app_repo)
                    
                    # Fallback to flat if nested doesn't exist but flat does
                    if not _branch_exists(r, r_branch):
                        if _branch_exists(r, branch):
                            r_branch = branch
                        else:
                            # Only prompt to create if they choice to create
                            missing_repos.append(r.name)
                            
                    resolved_branches[r.name] = r_branch

                # Prompt user if missing repos exist and no decision made yet
                create_missing_map = data.get("createMissingMap")
                if missing_repos and create_missing_map is None:
                    return {
                        "success": True,
                        "prompt": True,
                        "branch": branch,
                        "missingRepos": missing_repos
                    }

                failed_repos = []
                success_count = 0
                for r in scope_repos:
                    choice = create_missing_map.get(r.name) if create_missing_map is not None else None
                    r_branch = resolved_branches.get(r.name, branch)
                    ok, res = _checkout_one_repo(r, r_branch, choice)
                    if not ok:
                        failed_repos.append(f"{r.name}: {res}")
                    else:
                        success_count += 1

                if failed_repos:
                    return {"success": False, "error": f"Checkout failed on some repositories:\n" + "\n".join(failed_repos)}
                
                # Resolve actual active branch in target repo
                _, active_b, _ = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
                return {"success": True, "message": f"Successfully checked out {active_b} across {success_count} repositories."}

            else:
                # Single repo checkout
                create_missing_map = data.get("createMissingMap")
                if not _branch_exists(target, branch) and create_missing_map is None:
                    return {
                        "success": True,
                        "prompt": True,
                        "branch": branch,
                        "missingRepos": [target.name]
                    }

                choice = create_missing_map.get(target.name) if create_missing_map is not None else None
                ok, res = _checkout_one_repo(target, branch, choice)
                if not ok:
                    return {"success": False, "error": res}
                return {"success": True, "message": f"Successfully switched to branch {res}."}

        elif action == "rename":
            new_branch = str(data.get("newBranch") or "").strip()
            remote = bool(data.get("remote", False))
            if not new_branch:
                return {"success": False, "error": "Missing newBranch"}
            if new_branch == branch:
                return {"success": False, "error": "New branch name must be different from the current branch"}

            if _git_is_dirty(target):
                return {"success": False, "error": "Working tree has uncommitted changes. Please commit or stash them first."}

            use_melos = data.get("useMelos") is True
            app_name = _get_melos_app_name(target) if use_melos else ""

            if app_name:
                app_prefix = app_name.lower().replace("_", "-") + "-"
                scope_repos = _get_repos_in_melos_scope(app_name)
                failed_repos = []
                success_count = 0
                for r in scope_repos:
                    r_old_branch = branch
                    r_new_branch = new_branch
                    is_app_repo = ("/apps/" in str(r.as_posix())) or (r == target)

                    if app_prefix:
                        clean_app = app_prefix.rstrip("-")
                        
                        # Translate old branch name
                        parts_old = branch.split("/")
                        if len(parts_old) > 1:
                            has_app_segment = (parts_old[1] == clean_app)
                            has_app_dash_prefix = parts_old[1].startswith(app_prefix)
                            if is_app_repo:
                                if has_app_segment:
                                    parts_old.pop(1)
                                elif has_app_dash_prefix:
                                    parts_old[1] = parts_old[1][len(app_prefix):]
                            else:
                                if not has_app_segment and not has_app_dash_prefix:
                                    parts_old.insert(1, clean_app)
                                elif has_app_dash_prefix:
                                    v_scope = parts_old[1][len(app_prefix):]
                                    parts_old[1] = clean_app
                                    parts_old.insert(2, v_scope)
                            r_old_branch = "/".join(parts_old)

                        # Translate new branch name
                        parts_new = new_branch.split("/")
                        if len(parts_new) > 1:
                            has_app_segment = (parts_new[1] == clean_app)
                            has_app_dash_prefix = parts_new[1].startswith(app_prefix)
                            if is_app_repo:
                                if has_app_segment:
                                    parts_new.pop(1)
                                elif has_app_dash_prefix:
                                    parts_new[1] = parts_new[1][len(app_prefix):]
                            else:
                                if not has_app_segment and not has_app_dash_prefix:
                                    parts_new.insert(1, clean_app)
                                elif has_app_dash_prefix:
                                    v_scope = parts_new[1][len(app_prefix):]
                                    parts_new[1] = clean_app
                                    parts_new.insert(2, v_scope)
                            r_new_branch = "/".join(parts_new)

                    # Check if repo has the branch (try nested name first, fallback to flat name)
                    code_l, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{r_old_branch}"])
                    actual_old_branch = r_old_branch
                    if code_l != 0:
                        code_f, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{branch}"])
                        if code_f != 0:
                            continue  # Skip repos that do not have this branch under either name
                        actual_old_branch = branch
                    
                    # Check dirty
                    code_dirty, status_out, _ = _run_git(r, ["status", "--porcelain"])
                    if code_dirty == 0 and status_out.strip():
                        failed_repos.append(f"{r.name}: Working tree has uncommitted changes")
                        continue
                        
                    # Perform rename
                    code_ren, _, ren_err = _run_git(r, ["branch", "-m", actual_old_branch, r_new_branch])
                    if code_ren != 0:
                        failed_repos.append(f"{r.name}: {ren_err}")
                        continue
                        
                    # Handle remote rename if requested
                    if remote:
                        code_p, _, p_err = _run_git(r, ["push", "origin", r_new_branch])
                        if code_p != 0:
                            failed_repos.append(f"{r.name}: Local rename succeeded, but push failed: {p_err}")
                            continue
                        # Only delete old remote branch if it exists on remote
                        code_remote_exists, _, _ = _run_git(r, ["ls-remote", "--exit-code", "origin", actual_old_branch])
                        if code_remote_exists == 0:
                            code_d, _, d_err = _run_git(r, ["push", "origin", "--delete", actual_old_branch])
                            if code_d != 0:
                                failed_repos.append(f"{r.name}: Old remote deletion failed: {d_err}")
                                continue
                                
                    success_count += 1
                    
                if failed_repos:
                    return {"success": False, "error": f"Rename failed on some repositories:\n" + "\n".join(failed_repos)}
                return {"success": True, "message": f"Successfully renamed {branch} to {new_branch} across {success_count} repositories."}

            code, out, err = _run_git(target, ["branch", "-m", branch, new_branch], timeout=30)
            if code != 0:
                return {"success": False, "error": f"Rename failed: {err or out}"}
            if remote:
                code_p, out_p, err_p = _run_git(target, ["push", "origin", new_branch], timeout=120)
                if code_p != 0:
                    return {"success": False, "error": f"Local rename succeeded, but push failed: {err_p or out_p}"}
                code_d, out_d, err_d = _run_git(target, ["push", "origin", "--delete", branch], timeout=120)
                if code_d != 0:
                    return {"success": False, "error": f"Remote new branch pushed, but delete old branch failed: {err_d or out_d}"}

            return {"success": True, "message": f"Successfully renamed {branch} to {new_branch}."}

        elif action == "merge":
            target_branch = str(data.get("targetBranch") or "").strip()
            if not target_branch:
                return {"success": False, "error": "Missing targetBranch"}
            if target_branch == branch:
                return {"success": False, "error": "Cannot merge branch into itself"}

            use_melos = data.get("useMelos") is True
            push_after = data.get("push", True) is not False
            app_name = _get_melos_app_name(target) if use_melos else ""
            no_op_warnings = []

            def _merge_one_repo(r: Path, src_branch: str, tgt_branch: str) -> tuple[bool, str]:
                """Merge src_branch into tgt_branch for a single repo. Returns (ok, error_msg)."""
                is_app_repo = ("/apps/" in str(r.as_posix())) or (r == target)
                r_src_branch = _translate_branch_name(src_branch, app_name, is_app_repo)
                r_tgt_branch = _translate_branch_name(tgt_branch, app_name, is_app_repo)

                # Save current HEAD
                code_head, head_branch, _ = _run_git(r, ["rev-parse", "--abbrev-ref", "HEAD"])
                orig_branch = head_branch.strip() if code_head == 0 else ""

                # Check working tree is clean
                code_dirty, dirty_out, _ = _run_git(r, ["status", "--porcelain"])
                if code_dirty == 0 and dirty_out.strip():
                    return False, "Working tree has uncommitted changes"

                # Fetch to ensure we have latest remote refs
                _run_git(r, ["fetch", "origin"], timeout=60)

                # Resolve actual source branch name using fallback
                actual_src_branch = r_src_branch
                code_src_local, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{r_src_branch}"])
                code_src_remote, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{r_src_branch}"])
                if code_src_local != 0 and code_src_remote != 0:
                    code_flat_local, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{src_branch}"])
                    code_flat_remote, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{src_branch}"])
                    if code_flat_local == 0 or code_flat_remote == 0:
                        actual_src_branch = src_branch
                    else:
                        return True, ""  # Skip silently if branch doesn't exist

                # Update source branch to ensure it contains latest remote commits
                if orig_branch == actual_src_branch:
                    _run_git(r, ["pull", "origin", actual_src_branch, "--ff-only"], timeout=30)
                else:
                    _run_git(r, ["fetch", "origin", f"{actual_src_branch}:{actual_src_branch}"], timeout=30)

                # Resolve actual target branch name using fallback
                actual_tgt_branch = r_tgt_branch
                code_tgt_local, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{r_tgt_branch}"])
                code_tgt_remote, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{r_tgt_branch}"])
                if code_tgt_local != 0 and code_tgt_remote != 0:
                    code_flat_local, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/heads/{tgt_branch}"])
                    code_flat_remote, _, _ = _run_git(r, ["show-ref", "--quiet", f"refs/remotes/origin/{tgt_branch}"])
                    if code_flat_local == 0 or code_flat_remote == 0:
                        actual_tgt_branch = tgt_branch
                    else:
                        return False, f"Target branch {tgt_branch} (or nested {r_tgt_branch}) does not exist in {r.name}"

                # Check if the source branch is already an ancestor of the target branch (already merged)
                code_anc, _, _ = _run_git(r, ["merge-base", "--is-ancestor", actual_src_branch, actual_tgt_branch])
                if code_anc == 0:
                    # Check if target branch has subsequent commits that could have overridden changes
                    _, count_str, _ = _run_git(r, ["rev-list", "--count", f"{actual_src_branch}..{actual_tgt_branch}"])
                    num_subsequent = int(count_str.strip()) if count_str.strip().isdigit() else 0
                    if num_subsequent > 0:
                        _, log_str, _ = _run_git(r, ["log", "-n", "1", "--oneline", actual_tgt_branch])
                        log_info = f" (Latest: {log_str.strip()})" if log_str.strip() else ""
                        
                        no_op_warnings.append({
                            "repo": r.name,
                            "message": (
                                f"The source branch '{src_branch}' (or translated '{actual_src_branch}') is already fully merged into '{tgt_branch}'.\n"
                                f"However, the target branch has progressed by {num_subsequent} commit(s) since then{log_info}.\n"
                                f"If features are missing, they may have been reverted, overridden, or deleted in subsequent changes (e.g. by merging 'main')."
                            ),
                        })

                # Checkout target branch
                code_co, _, co_err = _run_git(r, ["checkout", actual_tgt_branch], timeout=30)
                if code_co != 0:
                    # Try to track remote target branch
                    code_co2, _, co_err2 = _run_git(r, ["checkout", "-b", actual_tgt_branch, f"origin/{actual_tgt_branch}"], timeout=30)
                    if code_co2 != 0:
                        return False, f"Cannot checkout {actual_tgt_branch}: {co_err2 or co_err}"

                # Pull latest target branch
                _run_git(r, ["pull", "origin", actual_tgt_branch, "--ff-only"], timeout=60)

                # Merge source into target
                code_merge, merge_out, merge_err = _run_git(r, ["merge", "--no-edit", "--no-ff", actual_src_branch], timeout=60)
                if code_merge != 0:
                    conflict = "conflict" in (merge_err + merge_out).lower()
                    _run_git(r, ["merge", "--abort"])
                    # Return to original branch
                    if orig_branch and orig_branch != actual_tgt_branch:
                        _run_git(r, ["checkout", orig_branch])
                    return False, f"{'Merge conflict' if conflict else 'Merge failed'}: {merge_err or merge_out}"

                # Push target branch to origin
                if push_after:
                    code_push, push_out, push_err = _run_git(r, ["push", "origin", actual_tgt_branch], timeout=120)
                    if code_push != 0:
                        # Roll back merge
                        _run_git(r, ["reset", "--hard", "HEAD~1"])
                        if orig_branch and orig_branch != actual_tgt_branch:
                            _run_git(r, ["checkout", orig_branch])
                        return False, f"Push failed: {push_err or push_out}"

                # Return to original branch
                if orig_branch and orig_branch != actual_tgt_branch:
                    _run_git(r, ["checkout", orig_branch])

                return True, ""

            if use_melos:
                if not app_name:
                    return {"success": False, "error": "Melos app name could not be resolved"}
                scope_repos = _get_repos_in_melos_scope(app_name)
                success_repos = []
                failed_repos = []
                for r in scope_repos:
                    ok, err_msg = _merge_one_repo(r, branch, target_branch)
                    if not ok:
                        failed_repos.append(f"{r.name}: {err_msg}")
                    else:
                        success_repos.append(r.name)

                if failed_repos:
                    return {"success": False, "error": "Merge failed on some repositories:\n" + "\n".join(failed_repos)}

                no_op_repo_names = [w["repo"] for w in no_op_warnings]
                merged_repo_names = [name for name in success_repos if name not in set(no_op_repo_names)]
                return {
                    "success": True,
                    "message": f"Successfully merged '{branch}' into '{target_branch}' across {len(success_repos)} repositories.",
                    "mergedRepos": merged_repo_names,
                    "noOpRepos": no_op_repo_names,
                    "noOpWarnings": [w["message"] for w in no_op_warnings],
                }
            else:
                ok, err_msg = _merge_one_repo(target, branch, target_branch)
                if not ok:
                    return {"success": False, "error": f"Merge failed: {err_msg}"}
                no_op_repo_names = [w["repo"] for w in no_op_warnings]
                merged_repo_names = [] if no_op_repo_names else [target.name]
                return {
                    "success": True,
                    "message": f"Successfully merged '{branch}' into '{target_branch}'.",
                    "mergedRepos": merged_repo_names,
                    "noOpRepos": no_op_repo_names,
                    "noOpWarnings": [w["message"] for w in no_op_warnings],
                }

        else:
            return {"success": False, "error": f"Invalid action: {action}"}

def _get_pubspec_version(repo_dir: Path) -> Optional[str]:
    pubspec = repo_dir / "pubspec.yaml"
    if not pubspec.exists():
        return None
    try:
        content = pubspec.read_text(encoding="utf-8")
        match = re.search(r"^version:\s*([^\s#]+)", content, re.MULTILINE)
        return match.group(1).strip() if match else None
    except Exception:
        return None

def _git_tag_exists(repo_dir: Path, tag_name: str) -> bool:
    code, _, _ = _run_git(repo_dir, ["show-ref", "--quiet", f"refs/tags/{tag_name}"])
    return code == 0

def handle_git_tag_create(data: dict) -> dict:
    _set_git_auth_token(str(data.get("githubToken") or "").strip())
    repo_path = str(data.get("repoPath") or "").strip()
    raw_tag_name = str(data.get("tagName") or "").strip()
    message = str(data.get("message") or "").strip()
    push_to_remote = bool(data.get("pushToRemote", False))

    if not repo_path or not message:
        return {"success": False, "error": "Missing repoPath or message"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    # Determine base version from tag input or pubspec.yaml
    pubspec_v = _get_pubspec_version(target)
    base_version = raw_tag_name or pubspec_v or "1.0.0"
    app_tag_name = base_version if base_version.startswith("v") else f"v{base_version}"

    use_melos = data.get("useMelos") is True
    app_name = _get_melos_app_name(target) if use_melos else target.name
    app_slug = app_name.replace("_", "-")

    if use_melos and app_name:
        scope_repos, scope_error = _get_melos_release_repos(app_name, target)
        if scope_error:
            return {"success": False, "error": scope_error}
        results = []
        created_count = 0
        skipped_count = 0
        failed_count = 0

        for r in scope_repos:
            # Format tag name: App repo gets vX.Y.Z, Package repos get app-name-vX.Y.Z
            if r.resolve() == target.resolve():
                t_name = app_tag_name
            else:
                t_name = f"{app_slug}-{app_tag_name}"

            if _git_tag_exists(r, t_name):
                skipped_count += 1
                results.append({"repo": r.name, "tag": t_name, "status": "skipped", "reason": "Tag already exists"})
                continue

            code_t, _, err_t = _run_git(r, ["tag", "-a", t_name, "-m", message])
            if code_t != 0:
                failed_count += 1
                results.append({"repo": r.name, "tag": t_name, "status": "error", "reason": err_t})
                continue

            created_count += 1
            pushed = False
            if push_to_remote:
                code_p, _, err_p = _run_git(r, ["push", "origin", t_name], timeout=30)
                pushed = (code_p == 0)

            results.append({"repo": r.name, "tag": t_name, "status": "created", "pushed": pushed})

        if failed_count > 0:
            return {"success": False, "error": f"Failed to tag on some repositories ({failed_count} errors).", "results": results}

        return {
            "success": True,
            "message": f"Successfully processed release tags across {len(scope_repos)} repositories ({created_count} created, {skipped_count} skipped).",
            "appTagName": app_tag_name,
            "pkgTagPrefix": f"{app_slug}-",
            "createdCount": created_count,
            "skippedCount": skipped_count,
            "pushedToRemote": push_to_remote,
            "results": results
        }
    else:
        t_name = app_tag_name
        if _git_tag_exists(target, t_name):
            return {"success": True, "message": f"Tag '{t_name}' already exists on {target.name}.", "skipped": True}

        code, out, err = _run_git(target, ["tag", "-a", t_name, "-m", message])
        if code != 0:
            return {"success": False, "error": f"Failed to create tag: {err or out}"}

        pushed = False
        if push_to_remote:
            code_p, _, err_p = _run_git(target, ["push", "origin", t_name], timeout=30)
            if code_p != 0:
                return {"success": False, "error": f"Tag created locally, but failed to push to origin: {err_p}"}
            pushed = True

        return {
            "success": True,
            "message": f"Tag '{t_name}' created {'and pushed to remote' if pushed else 'locally'}.",
            "tagName": t_name,
            "pushed": pushed
        }

def _list_git_tags(repo_dir: Path) -> list[dict]:
    remote_tags = set()
    code_r, out_r, _ = _run_git(repo_dir, ["ls-remote", "--tags", "origin"], timeout=10)
    if code_r == 0:
        for line in out_r.splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                ref = parts[1]
                if ref.startswith("refs/tags/"):
                    tag_name = ref.replace("refs/tags/", "")
                    if tag_name.endswith("^{}"):
                        tag_name = tag_name[:-3]
                    remote_tags.add(tag_name)

    tags_list = []
    # Pull the full annotation body (%(contents)) directly out of for-each-ref instead of
    # firing one extra `git tag -l --format=%(contents) <name>` subprocess per tag — that
    # N+1 pattern was the main reason listing tags for a repo with many releases was slow.
    # %1f/%1e (unit/record separators, for-each-ref's two-hex-digit escape syntax — NOT
    # git log's %x1e form) are used instead of newlines/pipes since %(contents) is itself
    # multi-line and may contain literal "|" characters.
    code_l, out_l, _ = _run_git(
        repo_dir,
        ["for-each-ref", "--format=%(refname:short)%1f%(contents)%1f%(objectname)%1f%(creatordate:unix)%1e", "refs/tags"],
        timeout=10,
    )
    if code_l == 0 and out_l:
        for record in out_l.split("\x1e"):
            record = record.strip("\n")
            if not record.strip():
                continue
            parts = record.split("\x1f")
            if len(parts) >= 3:
                tag_name = parts[0].strip()
                message = parts[1].strip() or tag_name
                sha = parts[2].strip()
                date_str = parts[3].strip() if len(parts) > 3 else ""

                try:
                    timestamp = int(date_str) if date_str.isdigit() else 0
                except ValueError:
                    timestamp = 0

                tags_list.append({
                    "name": tag_name,
                    "message": message,
                    "sha": sha[:8],
                    "timestamp": timestamp,
                    "pushed": tag_name in remote_tags,
                    "repoName": repo_dir.name
                })

    tags_list.sort(key=lambda x: x["timestamp"], reverse=True)
    return tags_list

def handle_git_tags_list(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    use_melos = data.get("useMelos") is True

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    app_name = _get_melos_app_name(target) if use_melos else ""
    
    if use_melos and app_name:
        scope_repos, scope_error = _get_melos_release_repos(app_name, target)
        if scope_error:
            return {"success": False, "error": scope_error}
        all_tags = {}
        # Each repo needs its own `git ls-remote` network round-trip plus a local git call;
        # done sequentially that's one round-trip per dependent package, and melos scopes
        # here commonly span 15-20 of them — that serial wait is what made this modal feel
        # stuck on "Loading release tags..." Fan them out across a small thread pool instead
        # (I/O-bound subprocess calls, so threads — not multiprocessing — are the right tool).
        with ThreadPoolExecutor(max_workers=min(8, len(scope_repos)) or 1) as pool:
            per_repo_tags = list(pool.map(_list_git_tags, scope_repos))
        for r, r_tags in zip(scope_repos, per_repo_tags):
            for t in r_tags:
                tag_name = t["name"]
                base_version = tag_name
                prefix = f"{app_name.replace('_', '-')}-"
                if tag_name.startswith(prefix):
                    base_version = tag_name[len(prefix):]
                
                if base_version not in all_tags:
                    all_tags[base_version] = {
                        "version": base_version,
                        "message": t["message"],
                        "timestamp": t["timestamp"],
                        "pushed": True,
                        "repos": []
                    }
                
                all_tags[base_version]["repos"].append({
                    "repoName": r.name,
                    "repoPath": str(r),
                    "tagName": tag_name,
                    "pushed": t["pushed"],
                    "sha": t["sha"],
                    "message": t["message"]
                })
                if not t["pushed"]:
                    all_tags[base_version]["pushed"] = False

        grouped_tags = list(all_tags.values())
        grouped_tags.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"success": True, "tags": grouped_tags, "isMelos": True}
    else:
        r_tags = _list_git_tags(target)
        tags = []
        for t in r_tags:
            tags.append({
                "version": t["name"],
                "message": t["message"],
                "timestamp": t["timestamp"],
                "pushed": t["pushed"],
                "repos": [{
                    "repoName": target.name,
                    "repoPath": str(target),
                    "tagName": t["name"],
                    "pushed": t["pushed"],
                    "sha": t["sha"],
                    "message": t["message"]
                }]
            })
        return {"success": True, "tags": tags, "isMelos": False}

def handle_git_tag_edit(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    old_version = str(data.get("oldVersion") or "").strip()
    new_version = str(data.get("newVersion") or "").strip()
    message = str(data.get("message") or "").strip()
    use_melos = data.get("useMelos") is True

    if not repo_path or not old_version or not new_version or not message:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    app_name = _get_melos_app_name(target) if use_melos else target.name
    app_slug = app_name.replace("_", "-")
    
    old_app_tag = old_version if old_version.startswith("v") else f"v{old_version}"
    new_app_tag = new_version if new_version.startswith("v") else f"v{new_version}"

    if use_melos and app_name:
        scope_repos, scope_error = _get_melos_release_repos(app_name, target)
        if scope_error:
            return {"success": False, "error": scope_error}
        failed = []
        for r in scope_repos:
            if r.resolve() == target.resolve():
                old_t = old_app_tag
                new_t = new_app_tag
            else:
                old_t = f"{app_slug}-{old_app_tag}"
                new_t = f"{app_slug}-{new_app_tag}"

            if _git_tag_exists(r, old_t):
                code_a, _, err_a = _run_git(r, ["tag", "-a", new_t, old_t, "-m", message])
                if code_a != 0:
                    failed.append(f"{r.name}: {err_a}")
                    continue
                code_d, _, _ = _run_git(r, ["tag", "-d", old_t])
        
        if failed:
            return {"success": False, "error": "Rename failed on some repos: " + ", ".join(failed)}
        return {"success": True, "message": f"Successfully renamed local tags to {new_app_tag}."}
    else:
        if _git_tag_exists(target, old_app_tag):
            code_a, _, err_a = _run_git(target, ["tag", "-a", new_app_tag, old_app_tag, "-m", message])
            if code_a != 0:
                return {"success": False, "error": err_a}
            code_d, _, _ = _run_git(target, ["tag", "-d", old_app_tag])
        return {"success": True, "message": f"Successfully renamed local tag to {new_app_tag}."}

def handle_git_tag_delete(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    version = str(data.get("version") or "").strip()
    use_melos = data.get("useMelos") is True

    if not repo_path or not version:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    app_name = _get_melos_app_name(target) if use_melos else target.name
    app_slug = app_name.replace("_", "-")
    app_tag = version if version.startswith("v") else f"v{version}"

    if use_melos and app_name:
        scope_repos, scope_error = _get_melos_release_repos(app_name, target)
        if scope_error:
            return {"success": False, "error": scope_error}
        failed = []
        for r in scope_repos:
            t_name = app_tag if r.resolve() == target.resolve() else f"{app_slug}-{app_tag}"
            if _git_tag_exists(r, t_name):
                code_d, _, err_d = _run_git(r, ["tag", "-d", t_name])
                if code_d != 0:
                    failed.append(f"{r.name}: {err_d}")
        if failed:
            return {"success": False, "error": "Delete failed on: " + ", ".join(failed)}
        return {"success": True, "message": f"Successfully deleted local release tags for {version}."}
    else:
        if _git_tag_exists(target, app_tag):
            code_d, _, err_d = _run_git(target, ["tag", "-d", app_tag])
            if code_d != 0:
                return {"success": False, "error": err_d}
        return {"success": True, "message": f"Successfully deleted local tag '{app_tag}'."}

def handle_git_tag_push(data: dict) -> dict:
    _set_git_auth_token(str(data.get("githubToken") or "").strip())
    repo_path = str(data.get("repoPath") or "").strip()
    version = str(data.get("version") or "").strip()
    use_melos = data.get("useMelos") is True

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    app_name = _get_melos_app_name(target) if use_melos else ""
    app_slug = app_name.replace("_", "-") if app_name else ""
    app_tag = version if version.startswith("v") else f"v{version}" if version else ""

    if use_melos and app_name:
        scope_repos, scope_error = _get_melos_release_repos(app_name, target)
        if scope_error:
            return {"success": False, "error": scope_error}
        failed_repos = []
        success_count = 0
        for r in scope_repos:
            if app_tag:
                t_name = app_tag if r.resolve() == target.resolve() else f"{app_slug}-{app_tag}"
                cmd = ["push", "origin", t_name]
            else:
                cmd = ["push", "origin", "--tags"]
                
            code, _, err = _run_git(r, cmd, timeout=30)
            if code != 0:
                failed_repos.append(f"{r.name}: {err}")
            else:
                success_count += 1
        if failed_repos:
            return {"success": False, "error": f"Failed to push tags on some repositories:\n" + "\n".join(failed_repos)}
        return {"success": True, "message": f"Successfully pushed tags across {success_count} repositories to remote origin."}
    else:
        cmd = ["push", "origin", app_tag] if app_tag else ["push", "origin", "--tags"]
        code, out, err = _run_git(target, cmd, timeout=30)
        if code != 0:
            return {"success": False, "error": f"Failed to push tags: {err or out}"}
        return {"success": True, "message": f"Successfully pushed tags for {target.name} to remote origin."}

def handle_git_branch_create(data: dict) -> dict:
    _set_git_auth_token(str(data.get("githubToken") or "").strip())
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or "").strip()
    base_branch = str(data.get("baseBranch") or "").strip()

    if not repo_path or not branch_name or not base_branch:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    checkout = data.get("checkout") is not False
    use_melos = data.get("useMelos") is True
    app_name = _get_melos_app_name(target) if use_melos else ""

    # 1. Resolve scope repositories (main app + dependencies if Melos is enabled)
    scope_paths = []
    if app_name:
        scope_paths = _get_melos_scope_paths(app_name)

    if not scope_paths:
        scope_paths = [target]

    # Resolve each path to its unique git repository root to avoid duplicate branch creation on sub-packages in the same repo
    unique_repos = set()
    scope_paths_resolved = []
    for path in scope_paths:
        code_tr, out_tr, _ = _run_git(path, ["rev-parse", "--show-toplevel"], timeout=5)
        if code_tr == 0 and out_tr.strip():
            git_root = Path(out_tr.strip()).resolve()
            if git_root not in unique_repos:
                unique_repos.add(git_root)
                scope_paths_resolved.append(git_root)
        else:
            resolved_path = path.resolve()
            if resolved_path not in unique_repos:
                unique_repos.add(resolved_path)
                scope_paths_resolved.append(resolved_path)
    
    scope_paths = scope_paths_resolved

    # Clean app prefix to strip/add (e.g., 'my-app-')
    app_prefix = ""
    if app_name and app_name != "all":
        app_prefix = app_name.lower().replace("_", "-") + "-"

    # 2. Iterate and perform git branching commands on each resolved repository path
    failures = []
    created_repos = []

    for r_path in scope_paths:
        # Determine specific branch name for this repository path
        r_branch_name = branch_name
        is_app_repo = ("/apps/" in str(r_path.as_posix())) or (r_path == target)

        if app_prefix:
            clean_app = app_prefix.rstrip("-")
            parts = branch_name.split("/")
            if len(parts) > 1:
                has_app_segment = (parts[1] == clean_app)
                has_app_dash_prefix = parts[1].startswith(app_prefix)

                if is_app_repo:
                    if has_app_segment:
                        parts.pop(1)
                    elif has_app_dash_prefix:
                        parts[1] = parts[1][len(app_prefix):]
                else:
                    if not has_app_segment and not has_app_dash_prefix:
                        parts.insert(1, clean_app)
                    elif has_app_dash_prefix:
                        v_scope = parts[1][len(app_prefix):]
                        parts[1] = clean_app
                        parts.insert(2, v_scope)
                r_branch_name = "/".join(parts)

        # Execute git operations
        # a. Checkout base branch
        code, _, err = _run_git(r_path, ["checkout", base_branch])
        if code != 0:
            failures.append(f"{r_path.name}: Failed to checkout base branch '{base_branch}' ({err})")
            continue

        # b. Pull latest (best effort)
        _run_git(r_path, ["pull", "origin", base_branch], timeout=20)

        # c. Create/Checkout new branch
        if checkout:
            code_c, _, err_c = _run_git(r_path, ["checkout", "-b", r_branch_name])
        else:
            code_c, _, err_c = _run_git(r_path, ["branch", r_branch_name, base_branch])

        if code_c != 0:
            failures.append(f"{r_path.name}: Failed to create branch '{r_branch_name}' ({err_c})")
            continue

        # d. Push upstream
        code_p, _, err_p = _run_git(r_path, ["push", "-u", "origin", r_branch_name], timeout=30)
        if code_p != 0:
            # We don't fail the whole action if push fails (e.g. offline/permission), but we note it.
            failures.append(f"{r_path.name}: Created locally but push to origin failed ({err_p})")
        else:
            created_repos.append(r_path.name)

    if failures:
        # If some failed completely (e.g. base branch missing), return errors
        return {
            "success": len(failures) < len(scope_paths),
            "error": " | ".join(failures),
            "message": f"Partially processed. Created branches in {len(created_repos)} repos. Errors: {', '.join(failures)}"
        }

    action_verb = "created and checked out" if checkout else "created"
    return {
        "success": True,
        "message": f"Successfully {action_verb} branch on all {len(scope_paths)} repositories."
    }

def handle_git_branch_finish(data: dict) -> dict:
    _set_git_auth_token(str(data.get("githubToken") or "").strip())
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or "").strip()
    base_branch = str(data.get("baseBranch") or "").strip()

    if not repo_path or not branch_name or not base_branch:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    use_melos = data.get("useMelos") is True
    app_name = _get_melos_app_name(target) if use_melos else ""

    # 1. Resolve scope repositories (main app + dependencies if Melos is enabled)
    scope_paths = []
    if app_name:
        scope_paths = _get_melos_scope_paths(app_name)

    if not scope_paths:
        scope_paths = [target]

    # Resolve unique Git repository roots to avoid running commands multiple times on nested sub-packages
    unique_repos = set()
    scope_paths_resolved = []
    for path in scope_paths:
        code_tr, out_tr, _ = _run_git(path, ["rev-parse", "--show-toplevel"], timeout=5)
        if code_tr == 0 and out_tr.strip():
            git_root = Path(out_tr.strip()).resolve()
            if git_root not in unique_repos:
                unique_repos.add(git_root)
                scope_paths_resolved.append(git_root)
        else:
            resolved_path = path.resolve()
            if resolved_path not in unique_repos:
                unique_repos.add(resolved_path)
                scope_paths_resolved.append(resolved_path)
    
    scope_paths = scope_paths_resolved

    # Clean app prefix to strip/add (e.g., 'my-app-')
    app_prefix = ""
    if app_name and app_name != "all":
        app_prefix = app_name.lower().replace("_", "-") + "-"

    # 2. Iterate and perform git merge and deletion commands on each repository
    failures = []
    finished_repos = []

    for r_path in scope_paths:
        # Determine specific branch name for this repository path
        r_branch_name = branch_name
        is_app_repo = ("/apps/" in str(r_path.as_posix())) or (r_path == target)

        if app_prefix:
            clean_app = app_prefix.rstrip("-")
            parts = branch_name.split("/")
            if len(parts) > 1:
                has_app_segment = (parts[1] == clean_app)
                has_app_dash_prefix = parts[1].startswith(app_prefix)

                if is_app_repo:
                    if has_app_segment:
                        parts.pop(1)
                    elif has_app_dash_prefix:
                        parts[1] = parts[1][len(app_prefix):]
                else:
                    if not has_app_segment and not has_app_dash_prefix:
                        parts.insert(1, clean_app)
                    elif has_app_dash_prefix:
                        v_scope = parts[1][len(app_prefix):]
                        parts[1] = clean_app
                        parts.insert(2, v_scope)
                r_branch_name = "/".join(parts)

        # a. Checkout base branch
        code, _, err = _run_git(r_path, ["checkout", base_branch])
        if code != 0:
            failures.append(f"{r_path.name}: Failed to checkout base '{base_branch}' ({err})")
            continue

        # b. Pull latest base
        _run_git(r_path, ["pull", "origin", base_branch], timeout=20)

        # c. Merge branch name into base branch
        code_m, out_m, err_m = _run_git(r_path, ["merge", "--no-edit", r_branch_name])
        if code_m != 0:
            # Handle conflict
            if "conflict" in (err_m or out_m).lower():
                _run_git(r_path, ["merge", "--abort"])
                failures.append(f"{r_path.name}: Merge conflict aborted")
            else:
                failures.append(f"{r_path.name}: Merge failed ({err_m or out_m})")
            continue

        # d. Push base branch to origin
        code_p, _, err_p = _run_git(r_path, ["push", "origin", base_branch], timeout=30)
        if code_p != 0:
            failures.append(f"{r_path.name}: Push failed ({err_p})")
            continue

        # e. Delete local branch
        code_d, _, _ = _run_git(r_path, ["branch", "-d", r_branch_name])
        if code_d != 0:
            # Force delete if standard delete fails
            _run_git(r_path, ["branch", "-D", r_branch_name])

        # f. Delete remote branch on origin
        _run_git(r_path, ["push", "origin", "--delete", r_branch_name], timeout=30)
        
        finished_repos.append(r_path.name)

    if failures:
        return {
            "success": len(failures) < len(scope_paths),
            "error": " | ".join(failures),
            "message": f"Partially processed. Finished branches in {len(finished_repos)} repos. Errors: {', '.join(failures)}"
        }

    return {
        "success": True,
        "message": f"Successfully merged and deleted branch on all {len(scope_paths)} repositories."
    }

def serve_git_stashes(path: str) -> dict:
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(path).query)
    repo_path = (query.get("repoPath") or [""])[0]
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = _run_git(target, ["stash", "list"])
    if code != 0:
        return {"success": False, "error": f"Failed to list stashes: {err or out}"}

    stashes = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # stash@{0}: WIP on master: a1b2c3d Message
        parts = line.split(":", 2)
        if len(parts) >= 2:
            ref = parts[0].strip()
            desc = parts[1].strip()
            if len(parts) > 2:
                desc += ": " + parts[2].strip()
            stashes.append({
                "ref": ref,
                "description": desc
            })
    return {"success": True, "stashes": stashes}

def handle_git_stash_create(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    message = str(data.get("message") or "").strip()
    include_untracked = bool(data.get("includeUntracked", True))

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    cmd = ["stash", "push"]
    if include_untracked:
        cmd.append("-u")
    if message:
        cmd.extend(["-m", message])

    code, out, err = _run_git(target, cmd)
    if code != 0:
        return {"success": False, "error": f"Failed to create stash: {err or out}"}
    return {"success": True, "message": out.strip() or "Stash created successfully."}

def handle_git_stash_apply(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    ref = str(data.get("ref") or "").strip()

    if not repo_path or not ref:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = _run_git(target, ["stash", "apply", ref])
    if code != 0:
        return {"success": False, "error": f"Failed to apply stash: {err or out}"}
    return {"success": True, "message": "Stash applied successfully."}

def handle_git_stash_drop(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    ref = str(data.get("ref") or "").strip()

    if not repo_path or not ref:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = _run_git(target, ["stash", "drop", ref])
    if code != 0:
        return {"success": False, "error": f"Failed to drop stash: {err or out}"}
    return {"success": True, "message": "Stash dropped successfully."}

def handle_git_stash_pop(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    ref = str(data.get("ref") or "").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    cmd = ["stash", "pop"]
    if ref:
        cmd.append(ref)

    code, out, err = _run_git(target, cmd)
    if code != 0:
        return {"success": False, "error": f"Failed to pop stash: {err or out}"}
    return {"success": True, "message": "Stash popped successfully."}

def serve_git_branch_ci_status(path: str) -> dict:
    from urllib.parse import urlparse, parse_qs
    import urllib.request
    import json
    import os
    import re

    query = parse_qs(urlparse(path).query)
    repo_path = (query.get("repoPath") or [""])[0]
    branch_name = (query.get("branchName") or [""])[0]

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code_r, rem_url, _ = _run_git(target, ["remote", "get-url", "origin"], timeout=10)
    if code_r != 0 or not rem_url.strip():
        return {"success": False, "error": "No origin remote configured"}

    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?", rem_url)
    if not match:
        return {"success": False, "error": "Origin remote is not a GitHub URL"}

    owner, repo_name = match.groups()

    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/commits/{urllib.parse.quote(branch_name)}/check-runs"
    req = urllib.request.Request(api_url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Gitflow-Dashboard")

    token = os.getenv("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                payload = json.loads(response.read().decode('utf-8'))
                check_runs = payload.get("check_runs", [])

                if not check_runs:
                    return {"success": True, "status": "none", "runs": []}

                overall_conclusion = "success"
                has_pending = False
                runs_info = []
                for run in check_runs:
                    name = run.get("name", "Check")
                    status = run.get("status", "")
                    conclusion = run.get("conclusion")
                    html_url = run.get("html_url", "")

                    runs_info.append({
                        "name": name,
                        "status": status,
                        "conclusion": conclusion,
                        "url": html_url
                    })

                    if status in ("queued", "in_progress"):
                        has_pending = True
                    elif conclusion in ("failure", "timed_out", "action_required"):
                        overall_conclusion = "failure"
                    elif conclusion == "cancelled" and overall_conclusion != "failure":
                        overall_conclusion = "cancelled"

                status_result = "pending" if has_pending else overall_conclusion
                return {
                    "success": True,
                    "status": status_result,
                    "runs": runs_info
                }
            return {"success": False, "error": f"GitHub API responded with code {response.status}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def serve_git_conflicts(path: str) -> dict:
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(path).query)
    repo_path = (query.get("repoPath") or [""])[0]
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = _run_git(target, ["diff", "--name-only", "--diff-filter=U"])
    if code != 0:
        return {"success": False, "error": f"Failed to get conflicting files: {err or out}"}

    files = [line.strip() for line in out.splitlines() if line.strip()]
    return {"success": True, "conflicts": files}

def handle_git_conflict_resolve(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    file_path = str(data.get("file") or "").strip()
    strategy = str(data.get("strategy") or "").strip() # ours or theirs

    if not repo_path or not file_path or strategy not in ("ours", "theirs"):
        return {"success": False, "error": "Invalid parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    # Run git checkout --ours/--theirs -- <file>
    code, out, err = _run_git(target, ["checkout", f"--{strategy}", "--", file_path])
    if code != 0:
        return {"success": False, "error": f"Failed to checkout {strategy} for {file_path}: {err or out}"}

    # Run git add -- <file> to mark it resolved
    code_a, out_a, err_a = _run_git(target, ["add", "--", file_path])
    if code_a != 0:
        return {"success": False, "error": f"Failed to stage {file_path}: {err_a or out_a}"}

    return {"success": True, "message": f"Successfully resolved {file_path} using '{strategy}' strategy."}

def handle_git_branch_delete(data: dict) -> dict:
    _set_git_auth_token(str(data.get("githubToken") or "").strip())
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or "").strip()

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing parameters"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    use_melos = data.get("useMelos") is True
    app_name = _get_melos_app_name(target) if use_melos else ""

    # 1. Resolve scope repositories (main app + dependencies if Melos is enabled)
    scope_paths = []
    if app_name:
        scope_paths = _get_melos_scope_paths(app_name)

    if not scope_paths:
        scope_paths = [target]

    # Resolve unique Git repository roots
    unique_repos = set()
    scope_paths_resolved = []
    for path in scope_paths:
        code_tr, out_tr, _ = _run_git(path, ["rev-parse", "--show-toplevel"], timeout=5)
        if code_tr == 0 and out_tr.strip():
            git_root = Path(out_tr.strip()).resolve()
            if git_root not in unique_repos:
                unique_repos.add(git_root)
                scope_paths_resolved.append(git_root)
        else:
            resolved_path = path.resolve()
            if resolved_path not in unique_repos:
                unique_repos.add(resolved_path)
                scope_paths_resolved.append(resolved_path)
    
    scope_paths = scope_paths_resolved

    # Clean app prefix to strip/add (e.g., 'my-app-')
    app_prefix = ""
    if app_name and app_name != "all":
        app_prefix = app_name.lower().replace("_", "-") + "-"

    failures = []
    deleted_repos = []

    for r_path in scope_paths:
        # Determine specific branch name for this repository path
        r_branch_name = branch_name
        is_app_repo = ("/apps/" in str(r_path.as_posix())) or (r_path == target)

        if app_prefix:
            clean_app = app_prefix.rstrip("-")
            parts = branch_name.split("/")
            if len(parts) > 1:
                has_app_segment = (parts[1] == clean_app)
                has_app_dash_prefix = parts[1].startswith(app_prefix)

                if is_app_repo:
                    if has_app_segment:
                        parts.pop(1)
                    elif has_app_dash_prefix:
                        parts[1] = parts[1][len(app_prefix):]
                else:
                    if not has_app_segment and not has_app_dash_prefix:
                        parts.insert(1, clean_app)
                    elif has_app_dash_prefix:
                        v_scope = parts[1][len(app_prefix):]
                        parts[1] = clean_app
                        parts.insert(2, v_scope)
                r_branch_name = "/".join(parts)

        # a. Switch away if currently checked out
        code_c, cur_branch, _ = _run_git(r_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        if code_c == 0 and cur_branch.strip() == r_branch_name:
            code_co, _, _ = _run_git(r_path, ["checkout", "develop"])
            if code_co != 0:
                _run_git(r_path, ["checkout", "main"])

        # b. Delete local branch
        code_d, _, err_d = _run_git(r_path, ["branch", "-D", r_branch_name])
        if code_d != 0 and "not found" not in err_d.lower():
            failures.append(f"{r_path.name}: Failed to delete local branch ({err_d})")
            continue

        # c. Delete remote branch (best effort)
        _run_git(r_path, ["push", "origin", "--delete", r_branch_name], timeout=30)
        deleted_repos.append(r_path.name)

    if failures:
        return {
            "success": len(failures) < len(scope_paths),
            "error": " | ".join(failures),
            "message": f"Partially deleted. Deleted in {len(deleted_repos)} repos. Errors: {', '.join(failures)}"
        }

    return {
        "success": True,
        "message": f"Successfully deleted branch '{branch_name}' on all {len(scope_paths)} repositories."
    }

def handle_git_release_create(data: dict) -> dict:
    repo_path = str(data.get("repoPath") or "").strip()
    tag_name = str(data.get("tagName") or "").strip()
    name = str(data.get("name") or "").strip()
    body = str(data.get("body") or "").strip()
    draft = bool(data.get("draft", False))
    prerelease = bool(data.get("prerelease", False))
    custom_token = str(data.get("githubToken") or "").strip()

    if not repo_path or not tag_name or not name:
        return {"success": False, "error": "Missing parameters (repoPath, tagName, name)"}

    workspace_root = _WORKSPACE_ROOT
    repos = _discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code_r, rem_url, _ = _run_git(target, ["remote", "get-url", "origin"], timeout=10)
    if code_r != 0 or not rem_url.strip():
        return {"success": False, "error": "No remote origin configured"}

    import re
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?", rem_url)
    if not match:
        return {"success": False, "error": "Origin remote is not a GitHub repository"}

    owner, repo_name = match.groups()

    token = custom_token or os.getenv("GITHUB_TOKEN")
    if not token:
        return {"success": False, "error": "GitHub Personal Access Token is missing. Please provide it in the input field."}

    import urllib.request
    import json
    
    api_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
    payload = {
        "tag_name": tag_name,
        "target_commitish": "main",
        "name": name,
        "body": body,
        "draft": draft,
        "prerelease": prerelease
    }
    
    req = urllib.request.Request(api_url)
    req.method = "POST"
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Gitflow-Dashboard")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.data = json.dumps(payload).encode("utf-8")

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status in (200, 201):
                res_data = json.loads(response.read().decode("utf-8"))
                return {
                    "success": True,
                    "message": f"Successfully created GitHub release '{name}'!",
                    "htmlUrl": res_data.get("html_url")
                }
            return {"success": False, "error": f"GitHub API responded with code {response.status}"}
    except urllib.error.HTTPError as he:
        try:
            err_body = he.read().decode("utf-8")
            err_json = json.loads(err_body)
            msg = err_json.get("message", err_body)
        except Exception:
            msg = str(he)
        return {"success": False, "error": f"GitHub API Error: {msg}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
