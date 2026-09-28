import os
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
    """
    Executes a git command safely within specified repository.
    Only passes token if provided explicitly for this request.
    """
    cmd = ["git", "-C", str(repo)] + args
    extra_env = {}
    if token:
        extra_env["GITHUB_TOKEN"] = token
        extra_env["GH_TOKEN"] = token
        
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

    # Stash count
    c_stash, out_stash, _ = run_git(repo, ["stash", "list"])
    stash_count = len(out_stash.strip().splitlines()) if (c_stash == 0 and out_stash.strip()) else 0

    # Dirty status
    c_status, out_status, _ = run_git(repo, ["status", "--porcelain"])
    dirty = (c_status == 0 and bool(out_status.strip()))
    changes_count = len(out_status.strip().splitlines()) if dirty else 0

    # Conflicts
    c_conf, out_conf, _ = run_git(repo, ["diff", "--name-only", "--diff-filter=U"])
    has_conflicts = (c_conf == 0 and bool(out_conf.strip()))

    # Ahead / Behind
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
    }
