import logging
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git

logger = logging.getLogger("devgit.staging")


def serve_git_status_files(path_str: str) -> Dict[str, Any]:
    """Return categorized lists of staged, unstaged, and untracked files for a repository."""
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

    code, out, err = run_git(target, ["status", "--porcelain=v1", "-uall"], strip=False)
    if code != 0:
        return {"success": False, "error": err or "Failed to read git status"}

    staged: List[Dict[str, str]] = []
    unstaged: List[Dict[str, str]] = []
    untracked: List[Dict[str, str]] = []

    status_labels = {
        "M": "Modified",
        "A": "Added",
        "D": "Deleted",
        "R": "Renamed",
        "C": "Copied",
        "U": "Unmerged",
        "?": "Untracked",
    }

    for line in out.splitlines():
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        file_path = line[3:].strip()
        if " -> " in file_path:
            file_path = file_path.split(" -> ")[1].strip()

        # Staged files (index has a change other than ?, space, or U)
        if index_status not in (" ", "?", "U"):
            staged.append({
                "path": file_path,
                "status": index_status,
                "label": status_labels.get(index_status, index_status)
            })

        # Unstaged modified / deleted files (worktree has a change other than space or ?)
        if worktree_status not in (" ", "?"):
            unstaged.append({
                "path": file_path,
                "status": worktree_status,
                "label": status_labels.get(worktree_status, worktree_status)
            })

        # Untracked files
        if index_status == "?" and worktree_status == "?":
            untracked.append({
                "path": file_path,
                "status": "?",
                "label": "Untracked"
            })

    return {
        "success": True,
        "repo": str(target),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "totalChanges": len(staged) + len(unstaged) + len(untracked)
    }


def handle_git_stage(data: dict) -> Dict[str, Any]:
    """Perform file-level staging operations (stage, unstage, discard)."""
    repo_path = str(data.get("repoPath") or "").strip()
    action = str(data.get("action") or "stage").strip().lower()  # stage | unstage | discard | stage_all | unstage_all
    files = data.get("files", [])

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    if action == "stage_all":
        code, out, err = run_git(target, ["add", "-A"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to stage all files"}
        return {"success": True, "message": "All changes staged."}

    if action == "unstage_all":
        code, out, err = run_git(target, ["reset", "HEAD"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to unstage all files"}
        return {"success": True, "message": "All changes unstaged."}

    if not isinstance(files, list) or not files:
        return {"success": False, "error": "No files provided"}

    # Sanitize file paths
    clean_files = []
    for f in files:
        f_str = str(f).strip()
        if not f_str or f_str.startswith("-") or ".." in f_str:
            continue
        clean_files.append(f_str)

    if not clean_files:
        return {"success": False, "error": "No valid file paths provided"}

    if action == "stage":
        cmd = ["add", "--"] + clean_files
        code, out, err = run_git(target, cmd)
        if code != 0:
            return {"success": False, "error": err or out or "Failed to stage files"}
        return {"success": True, "message": f"Staged {len(clean_files)} file(s)."}

    elif action == "unstage":
        cmd = ["restore", "--staged", "--"] + clean_files
        code, out, err = run_git(target, cmd)
        if code != 0:
            # Fallback for older git versions: git reset HEAD -- <files>
            code, out, err = run_git(target, ["reset", "HEAD", "--"] + clean_files)
            if code != 0:
                return {"success": False, "error": err or out or "Failed to unstage files"}
        return {"success": True, "message": f"Unstaged {len(clean_files)} file(s)."}

    elif action == "discard":
        # Discard tracked modifications
        cmd = ["restore", "--"] + clean_files
        code, out, err = run_git(target, cmd)
        if code != 0:
            # Also try checkout -- <files>
            code, out, err = run_git(target, ["checkout", "--"] + clean_files)
        # Also clean untracked if any
        run_git(target, ["clean", "-f", "--"] + clean_files)
        return {"success": True, "message": f"Discarded changes for {len(clean_files)} file(s)."}

    return {"success": False, "error": f"Invalid action: {action}"}
