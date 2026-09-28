import logging
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, validate_ref

logger = logging.getLogger("devgit.stash")


def serve_git_stashes(path_str: str) -> Dict[str, Any]:
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

    code, out, err = run_git(target, ["stash", "list", "--format=%(gd)|%(stashhash)|%(refname)|%(subject)"])
    if code != 0:
        return {"success": False, "error": err or "Failed to list stashes"}

    stashes = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        index_str = parts[0].strip()
        stash_hash = parts[1].strip() if len(parts) > 1 else ""
        subject = parts[-1].strip() if len(parts) > 2 else line
        stashes.append({
            "index": index_str,
            "hash": stash_hash,
            "message": subject
        })

    return {"success": True, "stashes": stashes, "repo": str(target)}


def handle_git_stash_create(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    message = str(data.get("message") or "").strip()
    include_untracked = data.get("includeUntracked", False)

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    cmd = ["stash", "push"]
    if include_untracked:
        cmd.append("-u")
    if message:
        cmd.extend(["-m", message])

    code, out, err = run_git(target, cmd)
    if code != 0:
        return {"success": False, "error": err or "Failed to create stash"}

    return {"success": True, "message": "Stash created successfully"}


def handle_git_stash_apply(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    stash_ref = str(data.get("stashRef") or data.get("index") or "stash@{0}").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    valid, reason = validate_ref(stash_ref)
    if not valid:
        return {"success": False, "error": f"Invalid stashRef: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["stash", "apply", "--", stash_ref])
    if code != 0:
        return {"success": False, "error": err or "Failed to apply stash"}

    return {"success": True, "message": f"Stash '{stash_ref}' applied successfully"}


def handle_git_stash_pop(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    stash_ref = str(data.get("stashRef") or data.get("index") or "stash@{0}").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    valid, reason = validate_ref(stash_ref)
    if not valid:
        return {"success": False, "error": f"Invalid stashRef: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["stash", "pop", "--", stash_ref])
    if code != 0:
        return {"success": False, "error": err or "Failed to pop stash"}

    return {"success": True, "message": f"Stash '{stash_ref}' popped successfully"}


def handle_git_stash_drop(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    stash_ref = str(data.get("stashRef") or data.get("index") or "stash@{0}").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    valid, reason = validate_ref(stash_ref)
    if not valid:
        return {"success": False, "error": f"Invalid stashRef: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["stash", "drop", "--", stash_ref])
    if code != 0:
        return {"success": False, "error": err or "Failed to drop stash"}

    return {"success": True, "message": f"Stash '{stash_ref}' dropped successfully"}


def handle_git_stash_pull_pop(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code_s, _, err_s = run_git(target, ["stash", "push", "-u", "-m", "DevGit Auto Stash before Pull"])
    if code_s != 0:
        return {"success": False, "error": f"Stash step failed: {err_s}"}

    code_p, _, err_p = run_git(target, ["pull"], token=token)
    if code_p != 0:
        return {"success": False, "error": f"Pull step failed: {err_p}. Stash saved."}

    code_pop, _, err_pop = run_git(target, ["stash", "pop"])
    if code_pop != 0:
        return {"success": False, "error": f"Stash pop had conflicts: {err_pop}"}

    return {"success": True, "message": "Stash -> Pull -> Pop completed successfully"}
