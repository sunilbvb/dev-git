import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git

logger = logging.getLogger("devgit.conflicts")


def serve_git_conflicts_list(path_str: str) -> Dict[str, Any]:
    """Return all unmerged / conflicted files in the repository."""
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

    code, out, err = run_git(target, ["diff", "--name-only", "--diff-filter=U"])
    conflicts = [f.strip() for f in out.splitlines() if f.strip()]

    # Also detect if a merge or rebase is actively in progress
    is_merging = (target / ".git" / "MERGE_HEAD").exists()
    is_rebasing = (target / ".git" / "rebase-merge").exists() or (target / ".git" / "rebase-apply").exists()
    is_cherry_picking = (target / ".git" / "CHERRY_PICK_HEAD").exists()

    operation = "none"
    if is_merging:
        operation = "merge"
    elif is_rebasing:
        operation = "rebase"
    elif is_cherry_picking:
        operation = "cherry-pick"

    return {
        "success": True,
        "repo": str(target),
        "conflicts": conflicts,
        "count": len(conflicts),
        "operation": operation,
        "inProgress": operation != "none"
    }


def serve_git_conflict_file(path_str: str) -> Dict[str, Any]:
    """Read conflicted file content and parse conflict blocks into structured ours/theirs chunks."""
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()
    file_path = (query.get("file") or [""])[0].strip()

    if not repo_path or not file_path:
        return {"success": False, "error": "Missing repoPath or file"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    full_path = (target / file_path).resolve()
    if not full_path.is_file() or target not in full_path.parents:
        return {"success": False, "error": "File does not exist or invalid path"}

    try:
        raw_text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"success": False, "error": f"Failed to read file: {e}"}

    # Parse conflict markers: <<<<<<<, =======, >>>>>>>
    marker_pattern = re.compile(
        r"<{7} [^\n]*\n(.*?)={7}\n(.*?)>{7} [^\n]*",
        re.DOTALL
    )

    blocks: List[Dict[str, str]] = []
    has_conflict_markers = False
    for match in marker_pattern.finditer(raw_text):
        has_conflict_markers = True
        ours_content = match.group(1)
        theirs_content = match.group(2)
        blocks.append({
            "ours": ours_content,
            "theirs": theirs_content
        })

    return {
        "success": True,
        "repo": str(target),
        "file": file_path,
        "rawContent": raw_text,
        "hasConflictMarkers": has_conflict_markers,
        "conflictBlocks": blocks,
        "conflictCount": len(blocks)
    }


def handle_git_conflict_resolve(data: dict) -> Dict[str, Any]:
    """Resolve a conflicted file using ours, theirs, or custom content."""
    repo_path = str(data.get("repoPath") or "").strip()
    file_path = str(data.get("file") or "").strip()
    strategy = str(data.get("strategy") or "ours").strip()  # ours | theirs | custom
    custom_content = data.get("content")

    if not repo_path or not file_path:
        return {"success": False, "error": "Missing repoPath or file"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    if strategy in ("ours", "theirs"):
        flag = "--ours" if strategy == "ours" else "--theirs"
        code, out, err = run_git(target, ["checkout", flag, "--", file_path])
        if code != 0:
            return {"success": False, "error": err or f"Failed to checkout {strategy} version"}
    elif strategy == "custom":
        if custom_content is None:
            return {"success": False, "error": "Missing custom content"}
        full_path = (target / file_path).resolve()
        if target not in full_path.parents:
            return {"success": False, "error": "Invalid file path"}
        try:
            full_path.write_text(str(custom_content), encoding="utf-8")
        except OSError as e:
            return {"success": False, "error": f"Failed to write file: {e}"}
    else:
        return {"success": False, "error": f"Invalid strategy: {strategy}"}

    code, out, err = run_git(target, ["add", "--", file_path])
    if code != 0:
        return {"success": False, "error": err or "Failed to stage resolved file"}

    # Check remaining conflicts
    code, out, _ = run_git(target, ["diff", "--name-only", "--diff-filter=U"])
    remaining = [f.strip() for f in out.splitlines() if f.strip()]

    return {
        "success": True,
        "message": f"Conflict resolved using '{strategy}' for {file_path}",
        "remainingConflicts": remaining,
        "allResolved": len(remaining) == 0
    }


def handle_git_conflict_abort(data: dict) -> Dict[str, Any]:
    """Abort active merge or rebase operation."""
    repo_path = str(data.get("repoPath") or "").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    # Check which operation is active and abort it
    if (target / ".git" / "MERGE_HEAD").exists():
        code, out, err = run_git(target, ["merge", "--abort"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to abort merge"}
        return {"success": True, "message": "Merge successfully aborted."}

    if (target / ".git" / "rebase-merge").exists() or (target / ".git" / "rebase-apply").exists():
        code, out, err = run_git(target, ["rebase", "--abort"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to abort rebase"}
        return {"success": True, "message": "Rebase successfully aborted."}

    if (target / ".git" / "CHERRY_PICK_HEAD").exists():
        code, out, err = run_git(target, ["cherry-pick", "--abort"])
        if code != 0:
            return {"success": False, "error": err or out or "Failed to abort cherry-pick"}
        return {"success": True, "message": "Cherry-pick successfully aborted."}

    return {"success": False, "error": "No merge or rebase in progress to abort."}
