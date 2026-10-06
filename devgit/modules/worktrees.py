import logging
import os
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, validate_ref

logger = logging.getLogger("devgit.worktrees")


def get_repo_worktrees(repo: Path) -> List[Dict[str, Any]]:
    code, out, _ = run_git(repo, ["worktree", "list", "--porcelain"])
    if code != 0 or not out.strip():
        return []

    worktrees: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            if current.get("path"):
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current.get("path"):
                worktrees.append(current)
                current = {}
            wt_path = line[9:].strip()
            current = {
                "path": wt_path,
                "name": Path(wt_path).name,
                "head": "",
                "branch": "",
                "bare": False,
                "locked": False,
                "lockReason": "",
                "prunable": False,
                "pruneReason": "",
                "isMain": len(worktrees) == 0,
            }
        elif line.startswith("HEAD "):
            current["head"] = line[5:].strip()
        elif line.startswith("branch "):
            ref = line[7:].strip()
            current["branch"] = ref.replace("refs/heads/", "")
        elif line == "detached":
            current["branch"] = "(detached)"
        elif line == "bare":
            current["bare"] = True
        elif line.startswith("locked"):
            current["locked"] = True
            current["lockReason"] = line[7:].strip()
        elif line.startswith("prunable"):
            current["prunable"] = True
            current["pruneReason"] = line[9:].strip()

    if current.get("path"):
        worktrees.append(current)

    return worktrees


def serve_git_worktrees(path_str: str) -> Dict[str, Any]:
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

    worktrees = get_repo_worktrees(target)
    return {
        "success": True,
        "repo": str(target),
        "worktrees": worktrees
    }


def handle_git_worktree_add(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    worktree_path_str = str(data.get("worktreePath") or data.get("path") or "").strip()
    branch = str(data.get("branch") or "").strip()
    new_branch = bool(data.get("newBranch", False))

    if not repo_path or not worktree_path_str:
        return {"success": False, "error": "Missing repoPath or worktreePath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    # Resolve target worktree path safely relative to repo or workspace
    if os.path.isabs(worktree_path_str):
        wt_path = Path(worktree_path_str).resolve()
    else:
        wt_path = (target.parent / worktree_path_str).resolve()

    if wt_path.exists() and any(wt_path.iterdir()):
        return {"success": False, "error": f"Target directory already exists and is not empty: {wt_path}"}

    args = ["worktree", "add"]
    if branch:
        valid, reason = validate_ref(branch)
        if not valid:
            return {"success": False, "error": f"Invalid branch: {reason}"}
        if new_branch:
            args.extend(["-b", branch, str(wt_path)])
        else:
            args.extend([str(wt_path), branch])
    else:
        args.append(str(wt_path))

    code, out, err = run_git(target, args)
    if code != 0:
        return {"success": False, "error": err or "Failed to add worktree"}

    return {
        "success": True,
        "message": f"Worktree created at {wt_path}",
        "worktreePath": str(wt_path),
        "branch": branch,
    }


def handle_git_worktree_remove(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    worktree_path_str = str(data.get("worktreePath") or data.get("path") or "").strip()
    force = bool(data.get("force", False))

    if not repo_path or not worktree_path_str:
        return {"success": False, "error": "Missing repoPath or worktreePath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    wt_path = Path(worktree_path_str).resolve()
    if wt_path == target:
        return {"success": False, "error": "Cannot remove the main repository worktree"}

    worktrees = get_repo_worktrees(target)
    matching = [wt for wt in worktrees if Path(wt["path"]).resolve() == wt_path]
    if not matching:
        return {"success": False, "error": f"Worktree not found on {target.name}: {wt_path}"}
    if matching[0].get("isMain"):
        return {"success": False, "error": "Cannot remove the main worktree"}

    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(wt_path))

    code, out, err = run_git(target, args)
    if code != 0:
        return {"success": False, "error": err or "Failed to remove worktree"}

    return {
        "success": True,
        "message": f"Worktree removed: {wt_path}",
        "worktreePath": str(wt_path)
    }


def handle_git_worktree_prune(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["worktree", "prune"])
    if code != 0:
        return {"success": False, "error": err or "Failed to prune worktrees"}

    return {
        "success": True,
        "message": "Pruned stale worktrees successfully"
    }
