import time
import logging
import threading
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, git_repo_status
from devgit.core.jobs import create_job, append_job_log, complete_job

logger = logging.getLogger("devgit.commits")

_GIT_LAST_FETCH: Dict[str, float] = {}


def serve_git_repos(path_str: str) -> Dict[str, Any]:
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    refresh = (query.get("refresh") or ["false"])[0].lower() == "true"

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    status_list = [git_repo_status(r) for r in repos]

    return {
        "success": True,
        "workspace": str(workspace_root),
        "repos": status_list
    }


def serve_git_user(path_str: str) -> Dict[str, Any]:
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()

    workspace_root = get_workspace_root()
    target = Path(repo_path).resolve() if repo_path else workspace_root

    code_name, name, _ = run_git(target, ["config", "user.name"])
    code_email, email, _ = run_git(target, ["config", "user.email"])

    return {
        "success": True,
        "name": name if code_name == 0 else "",
        "email": email if code_email == 0 else ""
    }


def serve_git_status(path_str: str) -> Dict[str, Any]:
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

    status = git_repo_status(target)
    return {"success": True, "status": status}


def serve_git_changes(path_str: str) -> Dict[str, Any]:
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

    code, out, err = run_git(target, ["status", "--porcelain"])
    if code != 0:
        return {"success": False, "error": err or "Failed to get changes"}

    files = []
    for line in out.splitlines():
        if not line or len(line) < 4:
            continue
        status_code = line[:2]
        filename = line[3:].strip()
        files.append({"status": status_code, "file": filename})

    return {"success": True, "files": files, "repo": str(target)}


def serve_git_diff(path_str: str) -> Dict[str, Any]:
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()
    file_path = (query.get("file") or [""])[0].strip()
    staged = (query.get("staged") or ["false"])[0].lower() == "true"

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    args = ["diff"]
    if staged:
        args.append("--staged")
    if file_path:
        args.extend(["--", file_path])

    code, out, err = run_git(target, args)
    return {"success": True, "diff": out, "repo": str(target)}


def serve_git_commits(path_str: str) -> Dict[str, Any]:
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()
    limit = int((query.get("limit") or ["30"])[0])

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["log", f"-n{limit}", "--format=%H|%an|%ae|%at|%s"])
    if code != 0:
        return {"success": False, "error": err or "Failed to get commits"}

    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 5:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "email": parts[2],
                "timestamp": int(parts[3]),
                "subject": parts[4],
            })

    return {"success": True, "commits": commits, "repo": str(target)}


def serve_git_branch_ci_status(path_str: str) -> Dict[str, Any]:
    return {"success": True, "ciStatus": "unknown"}


def serve_git_conflicts(path_str: str) -> Dict[str, Any]:
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
    return {"success": True, "conflicts": conflicts, "repo": str(target)}


def handle_git_commit_async(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    message = str(data.get("message") or "").strip()
    stage_all = data.get("stageAll", False)

    if not repo_path or not message:
        return {"success": False, "error": "Missing repoPath or message"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    if stage_all:
        run_git(target, ["add", "-A"])

    code, out, err = run_git(target, ["commit", "-m", message])
    if code != 0:
        return {"success": False, "error": err or "Failed to commit"}

    return {"success": True, "message": "Committed successfully"}


def handle_git_fetch(data: dict) -> Dict[str, Any]:
    scope = str(data.get("scope") or "all").strip().lower()
    repo_path = str(data.get("repoPath") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)

    selected: List[Path] = []
    if scope == "one":
        if not repo_path:
            return {"success": False, "error": "Missing repoPath"}
        target = Path(repo_path).resolve()
        if target not in repos:
            return {"success": False, "error": "Unknown repoPath"}
        selected = [target]
    else:
        selected = repos

    job_id = create_job("git_fetch", "git fetch")

    def _fetch():
        errors = []
        for r in selected:
            code, out, err = run_git(r, ["fetch"], token=token)
            if code != 0:
                errors.append(f"{r.name}: {err}")
                append_job_log(job_id, "error", f"Fetch failed on {r.name}: {err}\n")
            else:
                _GIT_LAST_FETCH[str(r)] = time.time()
                append_job_log(job_id, "output", f"Fetched {r.name}\n")

        if errors:
            complete_job(job_id, status="error", error_msg="; ".join(errors))
        else:
            complete_job(job_id, status="success")

    threading.Thread(target=_fetch, daemon=True).start()
    return {"success": True, "jobId": job_id}


def handle_git_pull(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    job_id = create_job("git_pull", f"git pull on {target.name}")

    def _pull():
        code, out, err = run_git(target, ["pull"], token=token)
        if code != 0:
            append_job_log(job_id, "error", err)
            complete_job(job_id, status="error", error_msg=err)
        else:
            append_job_log(job_id, "output", out)
            complete_job(job_id, status="success")

    threading.Thread(target=_pull, daemon=True).start()
    return {"success": True, "jobId": job_id}


def handle_git_push(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    token = str(data.get("githubToken") or "").strip()
    force = data.get("force", False)

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    job_id = create_job("git_push", f"git push on {target.name}")

    def _push():
        args = ["push", "--force-with-lease"] if force else ["push"]
        code, out, err = run_git(target, args, token=token)
        if code != 0:
            append_job_log(job_id, "error", err)
            complete_job(job_id, status="error", error_msg=err)
        else:
            append_job_log(job_id, "output", out)
            complete_job(job_id, status="success")

    threading.Thread(target=_push, daemon=True).start()
    return {"success": True, "jobId": job_id}


def handle_git_conflict_resolve(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    file_path = str(data.get("file") or "").strip()
    strategy = str(data.get("strategy") or "ours").strip()  # ours | theirs

    if not repo_path or not file_path:
        return {"success": False, "error": "Missing repoPath or file"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    flag = "--ours" if strategy == "ours" else "--theirs"
    code, out, err = run_git(target, ["checkout", flag, "--", file_path])
    if code != 0:
        return {"success": False, "error": err or f"Failed to checkout {strategy} version"}

    run_git(target, ["add", "--", file_path])
    return {"success": True, "message": f"Conflict resolved using '{strategy}' for {file_path}"}


def handle_git_contributors(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, out, err = run_git(target, ["shortlog", "-sn", "HEAD"])
    if code != 0:
        return {"success": False, "error": err or "Failed to list contributors"}

    contributors = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) == 2:
            try:
                count = int(parts[0])
                name = parts[1]
                contributors.append({"name": name, "commits": count})
            except ValueError:
                pass

    return {"success": True, "contributors": contributors, "repo": str(target)}
