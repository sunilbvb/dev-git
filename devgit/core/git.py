import os
import re
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("devgit.git")

_WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).expanduser().resolve()
_CACHE_FILE = Path(__file__).resolve().parent.parent / "git_repos_cache.json"


def set_workspace_root(path: Any) -> Path:
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = Path(path).expanduser().resolve()
    return _WORKSPACE_ROOT


def get_workspace_root() -> Path:
    return _WORKSPACE_ROOT


def validate_ref(ref_str: str) -> Tuple[bool, str]:
    if not ref_str or not isinstance(ref_str, str):
        return False, "Ref name cannot be empty"

    ref = ref_str.strip()
    if not ref:
        return False, "Ref name cannot be blank"

    if ref.startswith("-"):
        return False, f"Ref name '{ref}' cannot start with a dash ('-')"

    # Check for forbidden control chars & shell injection vectors
    if re.search(r"[\s;&|`$\\\n\r\t]", ref):
        return False, f"Ref name contains forbidden characters: '{ref}'"

    # Forbid directory traversal patterns and absolute / trailing slash paths
    if ref.startswith("/") or ref.endswith("/") or "//" in ref:
        return False, f"Ref name cannot start/end with slash or contain consecutive slashes: '{ref}'"
    if ref == ".." or ref == "." or ref.startswith("../") or "/../" in ref or ref.endswith("/.."):
        return False, f"Ref name cannot contain directory traversal: '{ref}'"

    # Handle stash ref format e.g. stash@{0}
    if ref.startswith("stash@{") and ref.endswith("}"):
        inner = ref[7:-1]
        if inner.isdigit():
            return True, ""
        return False, f"Invalid stash ref format: '{ref}'"

    # Check for ref range expressions (e.g. v1.0..v2.0 or HEAD~1..HEAD)
    if ".." in ref:
        parts = ref.split("..")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False, f"Invalid ref range: '{ref}'"
        ok_l, r_l = validate_ref(parts[0])
        if not ok_l:
            return False, f"Invalid ref in range '{parts[0]}': {r_l}"
        ok_r, r_r = validate_ref(parts[1])
        if not ok_r:
            return False, f"Invalid ref in range '{parts[1]}': {r_r}"
        return True, ""

    # Check for revision expressions (e.g. HEAD~1, main~2, commit^1)
    if "~" in ref or "^" in ref:
        if re.match(r"^[a-zA-Z0-9_\-./]+([~^]\d*)+$", ref):
            base = re.split(r"[~^]", ref, maxsplit=1)[0]
            ok_base, r_base = validate_ref(base)
            if ok_base:
                return True, ""
            return False, f"Invalid base ref in revision '{ref}': {r_base}"
        return False, f"Invalid revision syntax: '{ref}'"

    # Check git ref format for standard branch/tag names
    try:
        cmd = ["git", "check-ref-format", "--allow-onelevel", ref]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode != 0:
            return False, f"Invalid git ref format: '{ref}'"
    except Exception as e:
        logger.debug(f"git check-ref-format failed: {e}")

    return True, ""


def get_enhanced_env(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
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
    
    if extra_env:
        env.update(extra_env)
        
    return env


def run_git(repo: Path, args: List[str], timeout: int = 15, token: str = "") -> Tuple[int, str, str]:
    cmd = ["git", "-C", str(repo)]
    extra_env = {}
    
    if token:
        extra_env["GITHUB_TOKEN"] = token
        extra_env["GH_TOKEN"] = token
        cmd.extend([
            "-c",
            "credential.helper=!f() { echo username=x-access-token; echo password=$GITHUB_TOKEN; }; f"
        ])

    cmd.extend(args)
    env = get_enhanced_env(extra_env if extra_env else None)
    
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
    except subprocess.TimeoutExpired:
        logger.error(f"Git command timed out after {timeout}s: {' '.join(cmd)}")
        return 1, "", f"Command timed out after {timeout} seconds"
    except Exception as e:
        logger.exception(f"Error executing git command: {' '.join(cmd)}")
        return 1, "", str(e)


def discover_git_repos(workspace_root: Optional[Path] = None) -> List[Path]:
    root = (workspace_root or _WORKSPACE_ROOT).resolve()
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
            logger.warning(f"Error reading .devgit.json: {e}")

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
            dirnames[:] = [d for d in dirnames if d not in base_excludes]
            dp = Path(dirpath)
            if (dp / ".git").is_dir() or (dp / ".git").is_file():
                repos.add(dp.resolve())
                dirnames[:] = []
                
    return sorted(repos, key=lambda p: str(p))


def git_repo_status(repo: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    code, current_branch, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    active_branch = branch or (current_branch if code == 0 else "main")

    c_stash, out_stash, _ = run_git(repo, ["stash", "list"])
    stash_count = len(out_stash.strip().splitlines()) if (c_stash == 0 and out_stash.strip()) else 0

    c_status, out_status, _ = run_git(repo, ["status", "--porcelain"])
    dirty = (c_status == 0 and bool(out_status.strip()))
    changes_count = len(out_status.strip().splitlines()) if dirty else 0

    c_conf, out_conf, _ = run_git(repo, ["diff", "--name-only", "--diff-filter=U"])
    has_conflicts = (c_conf == 0 and bool(out_conf.strip()))

    ahead, behind = 0, 0
    c_ab, out_ab, _ = run_git(repo, ["rev-list", "--left-right", "--count", f"@{'{u}'}...HEAD"])
    if c_ab == 0 and out_ab:
        parts = out_ab.strip().split()
        if len(parts) == 2:
            try:
                behind = int(parts[0])
                ahead = int(parts[1])
            except ValueError:
                pass

    # Worktree detection
    is_worktree = (repo / ".git").is_file()
    worktree_count = 1
    main_worktree = None
    if is_worktree:
        try:
            git_content = (repo / ".git").read_text(encoding="utf-8").strip()
            if git_content.startswith("gitdir:"):
                gitdir_str = git_content[7:].strip()
                gitdir_path = Path(gitdir_str)
                if not gitdir_path.is_absolute():
                    gitdir_path = (repo / gitdir_path).resolve()
                if "worktrees" in gitdir_path.parts:
                    idx = gitdir_path.parts.index("worktrees")
                    main_git_dir = Path(*gitdir_path.parts[:idx])
                    main_worktree = str(main_git_dir.parent)
        except Exception:
            pass
    elif (repo / ".git" / "worktrees").is_dir():
        try:
            wt_subdirs = [p for p in (repo / ".git" / "worktrees").iterdir() if p.is_dir()]
            worktree_count = 1 + len(wt_subdirs)
        except Exception:
            worktree_count = 1

    return {
        "name": repo.name,
        "path": str(repo),
        "branch": active_branch,
        "dirty": dirty,
        "changes": changes_count,
        "ahead": ahead,
        "behind": behind,
        "conflict": has_conflicts,
        "stashCount": stash_count,
        "isWorktree": is_worktree,
        "mainWorktree": main_worktree,
        "worktreeCount": worktree_count,
    }
