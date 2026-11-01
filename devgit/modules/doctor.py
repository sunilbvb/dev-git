import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, validate_ref

logger = logging.getLogger("devgit.doctor")

PROTECTED_BRANCHES = {"main", "master", "develop"}
LARGE_FILE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB


def serve_git_doctor(path_str: str) -> Dict[str, Any]:
    """Audit repository health: stale merged branches, unpushed tags, large files, detached HEAD."""
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    checks: List[Dict[str, Any]] = []

    # 1. Check Detached HEAD
    code, head_ref, _ = run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
    is_detached = (code == 0 and head_ref.strip() == "HEAD")
    if is_detached:
        checks.append({
            "id": "detached_head",
            "type": "error",
            "title": "Detached HEAD State",
            "message": "Repository is not on a named branch. Commits made here may be lost.",
            "fixable": False
        })
    else:
        checks.append({
            "id": "detached_head",
            "type": "pass",
            "title": "Branch State",
            "message": f"Active branch is '{head_ref.strip()}'.",
            "fixable": False
        })

    # 2. Check Stale Merged Branches (> 30 days old)
    stale_branches: List[Dict[str, Any]] = []
    code, merged_out, _ = run_git(target, ["branch", "--merged", "main", "--format=%(refname:short)|%(committerdate:unix)"])
    if code == 0:
        now_ts = int(time.time())
        thirty_days = 30 * 86400
        for line in merged_out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            b_name = parts[0].strip()
            if b_name in PROTECTED_BRANCHES or "*" in b_name or not b_name:
                continue
            ts = 0
            if len(parts) > 1:
                try:
                    ts = int(parts[1])
                except ValueError:
                    pass
            is_stale = (now_ts - ts) > thirty_days if ts > 0 else False
            stale_branches.append({
                "name": b_name,
                "timestamp": ts,
                "isStale": is_stale
            })

    if stale_branches:
        stale_names = [b["name"] for b in stale_branches]
        checks.append({
            "id": "merged_branches",
            "type": "warning",
            "title": f"Merged Local Branches ({len(stale_names)})",
            "message": f"Branches already merged into main: {', '.join(stale_names)}",
            "details": stale_names,
            "fixable": True,
            "action": "delete_merged_branches"
        })
    else:
        checks.append({
            "id": "merged_branches",
            "type": "pass",
            "title": "Clean Branches",
            "message": "No obsolete merged branches found.",
            "fixable": False
        })

    # 3. Check Unpushed Tags
    local_tags: List[str] = []
    code, tag_out, _ = run_git(target, ["tag", "-l"])
    if code == 0 and tag_out:
        local_tags = [t.strip() for t in tag_out.splitlines() if t.strip()]

    remote_tags = set()
    code_r, out_r, _ = run_git(target, ["ls-remote", "--tags", "origin"], timeout=10)
    if code_r == 0:
        for line in out_r.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                t_name = parts[1][len("refs/tags/"):]
                if t_name.endswith("^{}"):
                    t_name = t_name[:-3]
                remote_tags.add(t_name)

        unpushed = [t for t in local_tags if t not in remote_tags]
        if unpushed:
            checks.append({
                "id": "unpushed_tags",
                "type": "warning",
                "title": f"Unpushed Local Tags ({len(unpushed)})",
                "message": f"Tags not yet pushed to origin: {', '.join(unpushed)}",
                "details": unpushed,
                "fixable": True,
                "action": "push_tags"
            })
        else:
            checks.append({
                "id": "unpushed_tags",
                "type": "pass",
                "title": "Tags Synchronized",
                "message": "All local tags exist on origin remote.",
                "fixable": False
            })

    # 4. Check for Large Files (> 10 MB)
    large_files: List[Dict[str, Any]] = []
    ignore_dirs = {".git", ".idea", "node_modules", ".venv", "build", "dist"}
    try:
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for file in files:
                f_path = Path(root) / file
                try:
                    size = f_path.stat().st_size
                    if size > LARGE_FILE_THRESHOLD_BYTES:
                        rel = str(f_path.relative_to(target))
                        large_files.append({"path": rel, "sizeMb": round(size / (1024 * 1024), 2)})
                except OSError:
                    pass
    except OSError:
        pass

    if large_files:
        checks.append({
            "id": "large_files",
            "type": "warning",
            "title": f"Large Files Detected ({len(large_files)})",
            "message": f"{len(large_files)} file(s) exceed 10 MB in working tree.",
            "details": large_files,
            "fixable": False
        })
    else:
        checks.append({
            "id": "large_files",
            "type": "pass",
            "title": "Repository Size",
            "message": "No oversized files (>10MB) detected.",
            "fixable": False
        })

    # Summary score
    errors = sum(1 for c in checks if c["type"] == "error")
    warnings = sum(1 for c in checks if c["type"] == "warning")
    health = "healthy" if errors == 0 and warnings == 0 else "warning" if errors == 0 else "critical"

    return {
        "success": True,
        "repo": str(target),
        "health": health,
        "checks": checks,
        "errorCount": errors,
        "warningCount": warnings
    }


def handle_git_doctor_fix(data: dict) -> Dict[str, Any]:
    """Execute automated cleanup fixes identified by Doctor."""
    repo_path = str(data.get("repoPath") or "").strip()
    action = str(data.get("action") or "").strip()
    target_item = str(data.get("item") or "").strip()

    if not repo_path or not action:
        return {"success": False, "error": "Missing repoPath or action"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    if action == "delete_branch":
        if not target_item:
            return {"success": False, "error": "Missing branch item"}
        if target_item in PROTECTED_BRANCHES:
            return {"success": False, "error": "Cannot delete protected branch"}
        valid, reason = validate_ref(target_item)
        if not valid:
            return {"success": False, "error": f"Invalid branch: {reason}"}

        code, out, err = run_git(target, ["branch", "-d", target_item])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to delete branch"}
        return {"success": True, "message": f"Deleted merged branch '{target_item}'."}

    if action == "prune_remote":
        code, out, err = run_git(target, ["remote", "prune", "origin"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to prune remote origin"}
        return {"success": True, "message": "Pruned obsolete remote tracking branches."}

    if action == "push_tags":
        code, out, err = run_git(target, ["push", "origin", "--tags"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to push tags"}
        return {"success": True, "message": "Pushed all local tags to origin."}

    return {"success": False, "error": f"Unknown action: {action}"}
