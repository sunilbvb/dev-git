import logging
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.git import get_workspace_root, discover_git_repos, run_git, git_repo_status
from core.jobs import create_job, append_job_log, complete_job

logger = logging.getLogger("devgit.branches")


def serve_git_branches(path_str: str) -> Dict[str, Any]:
    from urllib.parse import urlparse, parse_qs
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

    code, out, err = run_git(target, ["branch", "-a", "--format=%(refname:short)|%(HEAD)"])
    if code != 0:
        return {"success": False, "error": err or "Failed to list branches"}

    branches = []
    current_branch = ""
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        name = parts[0].strip()
        is_head = len(parts) > 1 and parts[1].strip() == "*"
        if is_head:
            current_branch = name
        branches.append({"name": name, "isCurrent": is_head})

    return {
        "success": True,
        "currentBranch": current_branch,
        "branches": branches,
        "repo": str(target)
    }


def handle_git_branch_create(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or data.get("name") or "").strip()
    checkout = data.get("checkout", True)

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing repoPath or branchName"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    args = ["checkout", "-b", branch_name] if checkout else ["branch", branch_name]
    code, out, err = run_git(target, args)
    if code != 0:
        return {"success": False, "error": err or "Failed to create branch"}

    return {"success": True, "message": f"Branch '{branch_name}' created successfully"}


def handle_git_branch_delete(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or data.get("name") or "").strip()
    force = data.get("force", False)

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing repoPath or branchName"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    flag = "-D" if force else "-d"
    code, out, err = run_git(target, ["branch", flag, branch_name])
    if code != 0:
        return {"success": False, "error": err or "Failed to delete branch"}

    return {"success": True, "message": f"Branch '{branch_name}' deleted successfully"}


def handle_git_branch_action(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or data.get("branch") or "").strip()
    action = str(data.get("action") or "").strip()  # checkout | merge | rebase

    if not repo_path or not branch_name or not action:
        return {"success": False, "error": "Missing repoPath, branchName, or action"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    if action == "checkout":
        code, out, err = run_git(target, ["checkout", branch_name])
    elif action == "merge":
        code, out, err = run_git(target, ["merge", branch_name])
    elif action == "rebase":
        code, out, err = run_git(target, ["rebase", branch_name])
    else:
        return {"success": False, "error": f"Invalid action: {action}"}

    if code != 0:
        return {"success": False, "error": err or f"Failed branch action {action}"}

    return {"success": True, "message": f"Branch action '{action}' on '{branch_name}' succeeded"}


def handle_git_sync_all_branches(data: dict) -> Dict[str, Any]:
    target_branch = str(data.get("targetBranch") or "main").strip()
    token = str(data.get("githubToken") or "").strip()
    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)

    job_id = create_job("git_sync_all", f"sync all repos to {target_branch}")

    def _sync():
        success_count = 0
        fail_count = 0
        for r in repos:
            append_job_log(job_id, "output", f"\n--- Syncing {r.name} ---\n")
            code, _, err = run_git(r, ["checkout", target_branch])
            if code != 0:
                append_job_log(job_id, "error", f"Checkout failed on {r.name}: {err}\n")
                fail_count += 1
                continue

            code_pull, out_pull, err_pull = run_git(r, ["pull"], token=token)
            if code_pull != 0:
                append_job_log(job_id, "error", f"Pull failed on {r.name}: {err_pull}\n")
                fail_count += 1
            else:
                append_job_log(job_id, "output", f"Successfully synced {r.name}\n")
                success_count += 1

        if fail_count == 0:
            complete_job(job_id, status="success")
        else:
            complete_job(job_id, status="error", error_msg=f"{fail_count} repo(s) failed sync")

    threading.Thread(target=_sync, daemon=True).start()
    return {"success": True, "jobId": job_id}
