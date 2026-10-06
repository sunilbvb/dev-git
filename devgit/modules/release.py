import logging
import re
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, validate_ref

logger = logging.getLogger("devgit.release")


def handle_git_tags_list(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["tag", "-l", "--sort=-creatordate", "--format=%(refname:short)|%(subject)|%(creatordate:iso)"])
    if code != 0:
        return {"success": False, "error": err or "Failed to list tags"}

    tags = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        tag_name = parts[0].strip()
        subject = parts[1].strip() if len(parts) > 1 else ""
        date = parts[2].strip() if len(parts) > 2 else ""
        tags.append({"name": tag_name, "message": subject, "date": date})

    return {"success": True, "tags": tags, "repo": str(target)}


def handle_git_tag_create(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    tag_name = str(data.get("tagName") or data.get("tag") or "").strip()
    message = str(data.get("message") or "").strip()

    if not repo_path or not tag_name:
        return {"success": False, "error": "Missing repoPath or tagName"}

    valid, reason = validate_ref(tag_name)
    if not valid:
        return {"success": False, "error": f"Invalid tagName: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    cmd = ["tag", "-a", tag_name, "-m", message or f"Release {tag_name}"] if message else ["tag", "--", tag_name]
    code, out, err = run_git(target, cmd)
    if code != 0:
        return {"success": False, "error": err or "Failed to create tag"}

    return {"success": True, "message": f"Tag '{tag_name}' created successfully"}


def handle_git_tag_delete(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    tag_name = str(data.get("tagName") or "").strip()

    if not repo_path or not tag_name:
        return {"success": False, "error": "Missing repoPath or tagName"}

    valid, reason = validate_ref(tag_name)
    if not valid:
        return {"success": False, "error": f"Invalid tagName: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["tag", "-d", "--", tag_name])
    if code != 0:
        return {"success": False, "error": err or "Failed to delete tag"}

    return {"success": True, "message": f"Tag '{tag_name}' deleted"}


def handle_git_tag_push(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    tag_name = str(data.get("tagName") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    if not repo_path or not tag_name:
        return {"success": False, "error": "Missing repoPath or tagName"}

    valid, reason = validate_ref(tag_name)
    if not valid:
        return {"success": False, "error": f"Invalid tagName: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["push", "origin", "--", tag_name], token=token)
    if code != 0:
        return {"success": False, "error": err or "Failed to push tag"}

    return {"success": True, "message": f"Tag '{tag_name}' pushed to remote"}


def handle_git_recommend_bump(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, _ = run_git(target, ["tag", "-l", "--sort=-v:refname"])
    tags = [t.strip() for t in out.splitlines() if t.strip()]

    latest_tag = tags[0] if tags else "v0.0.0"
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", latest_tag)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        recommended_patch = f"v{major}.{minor}.{patch + 1}"
        recommended_minor = f"v{major}.{minor + 1}.0"
        recommended_major = f"v{major + 1}.0.0"
    else:
        recommended_patch = "v0.0.1"
        recommended_minor = "v0.1.0"
        recommended_major = "v1.0.0"

    return {
        "success": True,
        "latestTag": latest_tag,
        "recommendations": {
            "patch": recommended_patch,
            "minor": recommended_minor,
            "major": recommended_major,
        }
    }


def handle_git_tags_compare(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    from_tag = str(data.get("fromTag") or "").strip()
    to_tag = str(data.get("toTag") or "HEAD").strip()

    if not repo_path or not from_tag:
        return {"success": False, "error": "Missing repoPath or fromTag"}

    valid_from, r_from = validate_ref(from_tag)
    if not valid_from:
        return {"success": False, "error": f"Invalid fromTag: {r_from}"}

    valid_to, r_to = validate_ref(to_tag)
    if not valid_to:
        return {"success": False, "error": f"Invalid toTag: {r_to}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["log", "--oneline", f"{from_tag}..{to_tag}"])
    if code != 0:
        return {"success": False, "error": err or "Failed to compare tags"}

    commits = [line.strip() for line in out.splitlines() if line.strip()]
    return {"success": True, "count": len(commits), "commits": commits}


def handle_git_tag_edit(data: dict) -> Dict[str, Any]:
    return {"success": False, "error": "Editing tags directly is not supported in Git; delete and recreate."}


def handle_git_release_create(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    tag_name = str(data.get("tagName") or "").strip()
    title = str(data.get("title") or tag_name).strip()
    body = str(data.get("body") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    if not repo_path or not tag_name:
        return {"success": False, "error": "Missing repoPath or tagName"}

    valid, reason = validate_ref(tag_name)
    if not valid:
        return {"success": False, "error": f"Invalid tagName: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    run_git(target, ["tag", "-a", tag_name, "-m", title])
    run_git(target, ["push", "origin", "--", tag_name], token=token)

    return {"success": True, "message": f"Release '{title}' with tag '{tag_name}' created"}
