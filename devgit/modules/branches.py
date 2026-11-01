import logging
import time
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from devgit.core.git import get_workspace_root, discover_git_repos, run_git, git_repo_status, validate_ref
from devgit.core.jobs import create_job, append_job_log, complete_job
from devgit.modules.release import _get_pubspec_version

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

    quick = (query.get("quick") or ["false"])[0] == "true"

    code, head, _ = run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
    head = head.strip() if code == 0 else ""

    branch_timestamps: Dict[str, int] = {}
    code, out_ts, _ = run_git(
        target,
        ["for-each-ref", "--format=%(refname:short)|%(committerdate:unix)", "refs/heads", "refs/remotes"],
        timeout=15,
    )
    if code == 0 and out_ts:
        for line in out_ts.splitlines():
            parts = line.strip().split("|")
            if len(parts) == 2:
                try:
                    branch_timestamps[parts[0]] = int(parts[1])
                except ValueError:
                    pass

    code, out, err = run_git(target, ["for-each-ref", "--format=%(refname:short)", "refs/heads"], timeout=15)
    if code != 0:
        return {"success": False, "error": err or "Failed to list branches"}
    branches = sorted(line.strip() for line in out.splitlines() if line.strip())

    branch_statuses: List[Dict[str, Any]] = []
    for b in branches:
        if quick:
            branch_statuses.append({
                "name": b, "hasUpstream": False, "upstream": "", "ahead": 0, "behind": 0,
                "isMerged": b == head, "updatedAt": branch_timestamps.get(b, 0),
            })
            continue

        status = git_repo_status(target, branch=b)
        is_merged = False
        if head and b != head:
            code_m, _, _ = run_git(target, ["merge-base", "--is-ancestor", b, head])
            if code_m == 0:
                upstream = status.get("upstream")
                if upstream:
                    code_um, _, _ = run_git(target, ["merge-base", "--is-ancestor", upstream, head])
                    is_merged = code_um == 0
                else:
                    is_merged = True
        branch_statuses.append({
            "name": b,
            "hasUpstream": bool(status.get("hasUpstream")),
            "upstream": status.get("upstream") or "",
            "ahead": status.get("ahead"),
            "behind": status.get("behind"),
            "isMerged": is_merged,
            "updatedAt": branch_timestamps.get(b, 0),
        })

    remote_branches: List[str] = []
    if not quick:
        code, out, _ = run_git(target, ["for-each-ref", "--format=%(refname:short)", "refs/remotes"], timeout=15)
        if code == 0 and out:
            remote_branches = sorted({
                v.strip() for v in out.splitlines()
                if v.strip() and "->" not in v and not v.strip().endswith("/HEAD") and v.strip() != "origin"
            })

        # Remote-only branches show up as "behind" so they can be pulled.
        local_set = set(branches)
        for rb in remote_branches:
            if not rb.startswith("origin/"):
                continue
            local_name = rb[len("origin/"):]
            if local_name in local_set or local_name == "HEAD":
                continue
            is_merged = False
            if head:
                code_m, _, _ = run_git(target, ["merge-base", "--is-ancestor", rb, head])
                is_merged = code_m == 0
            behind_count = 1
            code_c, counts, _ = run_git(target, ["rev-list", "--left-right", "--count", f"{rb}...HEAD"], timeout=12)
            if code_c == 0 and counts:
                try:
                    behind_count = int(counts.split()[0])
                except (ValueError, IndexError):
                    pass
            if behind_count > 0:
                branch_statuses.append({
                    "name": local_name, "hasUpstream": True, "upstream": rb, "ahead": 0,
                    "behind": behind_count, "isMerged": is_merged, "remoteOnly": True,
                    "updatedAt": branch_timestamps.get(rb, 0),
                })
                branches.append(local_name)
        branches = sorted(set(branches))

    return {
        "success": True,
        "repoPath": str(target),
        "repo": str(target),
        "head": head,
        "currentBranch": head,
        "branches": branches,
        "branchStatuses": branch_statuses,
        "remoteBranches": remote_branches,
        "quick": quick,
        "pubspecVersion": _get_pubspec_version(target) or "",
    }


def handle_git_branch_create(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or data.get("name") or "").strip()
    checkout = data.get("checkout", True)

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing repoPath or branchName"}

    valid, reason = validate_ref(branch_name)
    if not valid:
        return {"success": False, "error": f"Invalid branchName: {reason}"}

    if data.get("useMelos") is True:
        from devgit.modules.scoped_branch import handle_git_branch_create_scoped
        return handle_git_branch_create_scoped(data)

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    args = ["checkout", "-b", branch_name] if checkout else ["branch", "--", branch_name]
    code, out, err = run_git(target, args)
    if code != 0:
        return {"success": False, "error": err or "Failed to create branch"}

    return {"success": True, "message": f"Branch '{branch_name}' created successfully"}


PROTECTED_BRANCHES = {"main", "master", "develop"}


def handle_git_branch_finish(data: dict) -> Dict[str, Any]:
    """Gitflow finish: merge branch into base and push base. The branch is kept unless deleteBranch is true;
    protected branches (main/master/develop) are never deleted."""
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or "").strip()
    base_branch = str(data.get("baseBranch") or "").strip()
    token = str(data.get("githubToken") or "").strip()
    delete_branch = data.get("deleteBranch", True) is not False

    if not repo_path or not branch_name or not base_branch:
        return {"success": False, "error": "Missing parameters"}
    for label, ref in (("branchName", branch_name), ("baseBranch", base_branch)):
        valid, reason = validate_ref(ref)
        if not valid:
            return {"success": False, "error": f"Invalid {label}: {reason}"}
    if branch_name == base_branch:
        return {"success": False, "error": "Branch and base branch are the same"}

    repos = discover_git_repos(get_workspace_root())
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, _, err = run_git(target, ["checkout", base_branch])
    if code != 0:
        return {"success": False, "error": f"Failed to checkout base '{base_branch}': {err}"}

    run_git(target, ["pull", "origin", base_branch], timeout=20, token=token)

    code, out, err = run_git(target, ["merge", "--no-edit", branch_name])
    if code != 0:
        msg = err or out
        if "conflict" in msg.lower():
            run_git(target, ["merge", "--abort"])
            return {"success": False, "error": "Merge conflict; merge aborted"}
        return {"success": False, "error": f"Merge failed: {msg}"}

    code, _, err = run_git(target, ["push", "origin", base_branch], timeout=30, token=token)
    if code != 0:
        return {"success": False, "error": f"Merged locally but push failed: {err}"}

    if not delete_branch or branch_name in PROTECTED_BRANCHES:
        return {"success": True, "message": f"Merged '{branch_name}' into '{base_branch}'. Branch kept."}

    code, _, _ = run_git(target, ["branch", "-d", branch_name])
    if code != 0:
        run_git(target, ["branch", "-D", branch_name])
    run_git(target, ["push", "origin", "--delete", branch_name], timeout=30, token=token)

    return {"success": True, "message": f"Merged '{branch_name}' into '{base_branch}' and deleted the branch."}


def handle_git_branch_delete(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    branch_name = str(data.get("branchName") or data.get("name") or "").strip()
    force = data.get("force", False)

    if not repo_path or not branch_name:
        return {"success": False, "error": "Missing repoPath or branchName"}

    valid, reason = validate_ref(branch_name)
    if not valid:
        return {"success": False, "error": f"Invalid branchName: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    flag = "-D" if force else "-d"
    code, out, err = run_git(target, ["branch", flag, "--", branch_name])
    if code != 0:
        return {"success": False, "error": err or "Failed to delete branch"}

    return {"success": True, "message": f"Branch '{branch_name}' deleted successfully"}


def _ref_exists(repo: Path, ref: str) -> bool:
    return run_git(repo, ["show-ref", "--quiet", ref])[0] == 0


def _branch_exists(repo: Path, name: str) -> bool:
    return _ref_exists(repo, f"refs/heads/{name}") or _ref_exists(repo, f"refs/remotes/origin/{name}")


def _current_branch(repo: Path) -> str:
    code, out, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if code == 0 else ""


def _is_conflict(*texts: str) -> bool:
    return "conflict" in " ".join(t or "" for t in texts).lower()


def _checkout_branch(target: Path, name: str, create_if_missing: Optional[bool]) -> Dict[str, Any]:
    if _current_branch(target) == name:
        return {"success": True, "message": f"Already on branch {name}."}

    if _branch_exists(target, name):
        code, _, err = run_git(target, ["checkout", name])
        if code != 0:
            code, _, err2 = run_git(target, ["checkout", "-b", name, f"origin/{name}"])
            if code != 0:
                return {"success": False, "error": f"Failed to checkout {name}: {err2 or err}"}
        return {"success": True, "message": f"Successfully switched to branch {name}."}

    if create_if_missing is True:
        code, _, err = run_git(target, ["checkout", "-b", name])
        if code != 0:
            return {"success": False, "error": f"Failed to create branch {name}: {err}"}
        return {"success": True, "message": f"Successfully switched to branch {name}."}
    if create_if_missing is False:
        for fallback in ("develop", "main", "master"):
            if _branch_exists(target, fallback):
                code, _, err = run_git(target, ["checkout", fallback])
                if code != 0:
                    return {"success": False, "error": f"Failed to checkout fallback {fallback}: {err}"}
                return {"success": True, "message": f"Successfully switched to branch {fallback}."}
        return {"success": False, "error": f"Branch '{name}' not found, and no fallback branch found"}
    return {"success": False, "error": f"Branch '{name}' does not exist"}


def _checkout_scoped(app_repo: Path, branch: str, missing_map: Optional[dict], token: str) -> Dict[str, Any]:
    """Check out branch in the app repo and every repo of its dependent Melos packages.

    Packages use package_base_name() (main/master/develop are shared). Repos missing the branch are returned as a
    prompt (missingRepos) until createMissingMap says create (true) or fall back (false) for each of them."""
    from devgit.modules.scoped_branch import resolve_scope_repos, package_base_name

    workspace_root = get_workspace_root()
    ok, scope = resolve_scope_repos(app_repo, workspace_root, discover_git_repos(workspace_root))
    if not ok:
        return {"success": False, "error": f"Could not resolve dependent packages: {scope}"}

    plan = [(repo, branch if repo == app_repo else package_base_name(branch, app_repo)) for repo in scope["repos"]]
    for repo, _ in plan:
        run_git(repo, ["fetch", "origin"], timeout=60, token=token)

    missing = [repo.name for repo, name in plan if not _branch_exists(repo, name)]
    if missing and missing_map is None:
        return {"success": True, "prompt": True, "branch": branch, "missingRepos": missing}

    done: List[str] = []
    failed: List[str] = []
    for repo, name in plan:
        choice = missing_map.get(repo.name) if isinstance(missing_map, dict) else None
        res = _checkout_branch(repo, name, choice)
        if res["success"]:
            done.append(repo.name)
        else:
            failed.append(f"{repo.name} ({res['error']})")
    if failed:
        return {"success": False, "package": scope["package"], "switched": done,
                "error": "Checkout failed in " + "; ".join(failed)
                         + (f". Switched: {', '.join(done)}" if done else "")}
    return {"success": True, "package": scope["package"], "switched": done,
            "message": f"Switched {len(done)} repo(s) to '{branch}': {', '.join(done)}"}


def _merge_into(target: Path, source: str, dest: str, push_after: bool, token: str) -> Dict[str, Any]:
    """Pull dest, merge source into it (no fast-forward), optionally push dest, then return to the original branch."""
    orig = _current_branch(target)
    run_git(target, ["fetch", "origin"], timeout=60, token=token)

    if not _branch_exists(target, source):
        return {"success": False, "error": f"Source branch '{source}' does not exist"}
    if not _branch_exists(target, dest):
        return {"success": False, "error": f"Target branch '{dest}' does not exist"}

    # Bring the source branch up to date with origin when possible.
    if orig == source:
        run_git(target, ["pull", "origin", source, "--ff-only"], timeout=30, token=token)
    else:
        run_git(target, ["fetch", "origin", f"{source}:{source}"], timeout=30, token=token)

    def _back():
        if orig and orig != dest:
            run_git(target, ["checkout", orig])

    code, _, err = run_git(target, ["checkout", dest], timeout=30)
    if code != 0:
        code, _, err2 = run_git(target, ["checkout", "-b", dest, f"origin/{dest}"], timeout=30)
        if code != 0:
            return {"success": False, "error": f"Cannot checkout {dest}: {err2 or err}"}
    run_git(target, ["pull", "origin", dest, "--ff-only"], timeout=60, token=token)

    warnings = []
    if run_git(target, ["merge-base", "--is-ancestor", source, dest])[0] == 0:
        _, count, _ = run_git(target, ["rev-list", "--count", f"{source}..{dest}"])
        if count.strip().isdigit() and int(count.strip()) > 0:
            warnings.append(
                f"'{source}' is already fully merged into '{dest}', and '{dest}' has since progressed "
                f"by {count.strip()} commit(s). If changes seem missing they may have been reverted or overridden."
            )

    code, out, err = run_git(target, ["merge", "--no-edit", "--no-ff", source], timeout=60)
    if code != 0:
        conflict = _is_conflict(err, out)
        run_git(target, ["merge", "--abort"])
        _back()
        return {"success": False, "conflict": conflict,
                "error": f"{'Merge conflict' if conflict else 'Merge failed'}: {err or out}"}

    if push_after:
        code, out, err = run_git(target, ["push", "origin", dest], timeout=120, token=token)
        if code != 0:
            run_git(target, ["reset", "--hard", "HEAD~1"])
            _back()
            return {"success": False, "error": f"Push failed: {err or out}"}

    _back()
    return {"success": True, "message": f"Successfully merged '{source}' into '{dest}'.", "noOpWarnings": warnings}


def _merge_scoped(app_repo: Path, source: str, dest: str, push_after: bool, token: str) -> Dict[str, Any]:
    """Merge source into dest in the app repo and every repo of its dependent Melos packages.

    Packages use package_base_name() (main/master/develop are shared). Every repo is checked first (clean tree,
    both branches present) and nothing changes unless all pass; the run stops at the first failing repo."""
    from devgit.modules.scoped_branch import resolve_scope_repos, package_base_name

    workspace_root = get_workspace_root()
    ok, scope = resolve_scope_repos(app_repo, workspace_root, discover_git_repos(workspace_root))
    if not ok:
        return {"success": False, "error": f"Could not resolve dependent packages: {scope}"}

    plan = []
    for repo in scope["repos"]:
        is_app = repo == app_repo
        plan.append((repo, source if is_app else package_base_name(source, app_repo),
                     dest if is_app else package_base_name(dest, app_repo)))

    problems = []
    before: Dict[Path, str] = {}
    for repo, src, dst in plan:
        run_git(repo, ["fetch", "origin"], timeout=60, token=token)
        if run_git(repo, ["status", "--porcelain"])[1].strip():
            problems.append(f"{repo.name} (uncommitted changes)")
        elif not _branch_exists(repo, src):
            problems.append(f"{repo.name} (branch '{src}' missing)")
        elif not _branch_exists(repo, dst):
            problems.append(f"{repo.name} (branch '{dst}' missing)")
        else:
            before[repo] = run_git(repo, ["rev-parse", f"origin/{dst}"])[1].strip()
    if problems:
        return {"success": False, "package": scope["package"],
                "error": "Pre-check failed in " + ", ".join(problems) + "; nothing was changed"}

    merged: List[str] = []
    noop: List[str] = []
    warnings: List[str] = []
    for repo, src, dst in plan:
        res = _merge_into(repo, src, dst, push_after, token)
        if not res["success"]:
            return {"success": False, "package": scope["package"], "mergedRepos": merged, "noOpRepos": noop,
                    "error": f"Stopped at {repo.name}: {res['error']}. Earlier repos keep their merge."}
        if run_git(repo, ["rev-parse", dst])[1].strip() == before.get(repo):
            noop.append(repo.name)
            warnings.append(f"'{src}' is already merged into '{dst}'; nothing to apply.")
        else:
            merged.append(repo.name)
    return {"success": True, "package": scope["package"], "mergedRepos": merged, "noOpRepos": noop,
            "noOpWarnings": warnings if noop else [],
            "message": f"Merged '{source}' into '{dest}' in {len(merged)} repo(s); {len(noop)} already up to date."}


def handle_git_branch_action(data: dict) -> Dict[str, Any]:
    """Branch actions: pull, push, fetch, checkout, rename, merge, merge-current-into-this,
    merge-this-into-current, rebase. Operates on the selected repository only."""
    repo_path = str(data.get("repoPath") or "").strip()
    branch = str(data.get("branch") or data.get("branchName") or "").strip()
    action = str(data.get("action") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    if not repo_path or not branch or not action:
        return {"success": False, "error": "Missing parameters"}
    valid, reason = validate_ref(branch)
    if not valid:
        return {"success": False, "error": f"Invalid branchName: {reason}"}

    repos = discover_git_repos(get_workspace_root())
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, status_out, _ = run_git(target, ["status", "--porcelain"])
    if code != 0:
        return {"success": False, "error": "Failed to check git status"}
    if status_out.strip():
        return {"success": False, "dirty": True,
                "error": "Working tree has uncommitted changes. Please commit or stash them first."}

    current = _current_branch(target)
    if not current:
        return {"success": False, "error": "Failed to resolve current branch"}

    if action == "pull":
        if not _branch_exists(target, branch):
            return {"success": True, "message": f"Branch '{branch}' not found; nothing to pull."}
        code, _, err = run_git(target, ["checkout", branch])
        if code != 0:
            return {"success": False, "error": f"Failed to checkout {branch}: {err}"}
        code, out, err = run_git(target, ["pull", "origin", branch], timeout=60, token=token)
        conflict = code != 0 and _is_conflict(err, out)
        if conflict:
            run_git(target, ["merge", "--abort"])
        if current != branch:
            run_git(target, ["checkout", current])
        if code != 0:
            return {"success": False, "error": f"{'Merge conflict' if conflict else 'Pull failed'}: {err or out}"}
        return {"success": True, "message": f"Successfully pulled updates for {branch}."}

    if action == "push":
        if not _ref_exists(target, f"refs/heads/{branch}"):
            return {"success": True, "message": f"Branch '{branch}' not found locally; nothing to push."}
        code, out, err = run_git(target, ["push", "origin", branch], timeout=120, token=token)
        if code != 0:
            return {"success": False, "error": f"Push failed: {err or out}"}
        return {"success": True, "message": f"Successfully pushed updates for {branch}."}

    if action == "fetch":
        code, out, err = run_git(target, ["fetch", "origin"], timeout=120, token=token)
        if code != 0:
            return {"success": False, "error": f"Fetch failed: {err or out}"}
        return {"success": True, "message": "Successfully fetched updates from origin."}

    if action == "checkout":
        if data.get("useMelos") is True:
            return _checkout_scoped(target, branch, data.get("createMissingMap"), token)
        missing_map = data.get("createMissingMap")
        if not _branch_exists(target, branch) and missing_map is None:
            return {"success": True, "prompt": True, "branch": branch, "missingRepos": [target.name]}
        choice = missing_map.get(target.name) if isinstance(missing_map, dict) else None
        return _checkout_branch(target, branch, choice)

    if action == "rename":
        new_branch = str(data.get("newBranch") or "").strip()
        remote = bool(data.get("remote", False))
        if not new_branch:
            return {"success": False, "error": "Missing newBranch"}
        valid, reason = validate_ref(new_branch)
        if not valid:
            return {"success": False, "error": f"Invalid newBranch: {reason}"}
        if new_branch == branch:
            return {"success": False, "error": "New branch name must be different from the current branch"}
        code, out, err = run_git(target, ["branch", "-m", branch, new_branch], timeout=30)
        if code != 0:
            return {"success": False, "error": f"Rename failed: {err or out}"}
        if remote:
            code, out, err = run_git(target, ["push", "origin", new_branch], timeout=120, token=token)
            if code != 0:
                return {"success": False, "error": f"Local rename succeeded, but push failed: {err or out}"}
            code, out, err = run_git(target, ["push", "origin", "--delete", branch], timeout=120, token=token)
            if code != 0:
                return {"success": False,
                        "error": f"Remote new branch pushed, but delete old branch failed: {err or out}"}
        return {"success": True, "message": f"Successfully renamed {branch} to {new_branch}."}

    if action == "merge":
        dest = str(data.get("targetBranch") or "").strip()
        if not dest:
            return {"success": False, "error": "Missing targetBranch"}
        valid, reason = validate_ref(dest)
        if not valid:
            return {"success": False, "error": f"Invalid targetBranch: {reason}"}
        if dest == branch:
            return {"success": False, "error": "Cannot merge branch into itself"}
        push_after = data.get("push", True) is not False
        if data.get("useMelos") is True:
            return _merge_scoped(target, branch, dest, push_after, token)
        res = _merge_into(target, branch, dest, push_after, token)
        if not res["success"] and not str(res.get("error", "")).startswith(("Merge", "Push")):
            res["error"] = f"Merge failed: {res['error']}"
        return res

    if action == "merge-current-into-this":
        if branch == current:
            return {"success": False, "error": "Cannot merge branch into itself."}
        code, _, err = run_git(target, ["checkout", branch])
        if code != 0:
            return {"success": False, "error": f"Failed to checkout {branch}: {err}"}
        code, out, err = run_git(target, ["merge", "--no-edit", current])
        if code != 0:
            conflict = _is_conflict(err, out)
            if conflict:
                run_git(target, ["merge", "--abort"])
            run_git(target, ["checkout", current])
            return {"success": False, "conflict": conflict, "error": f"Merge failed: {err or out}"}
        code, _, err = run_git(target, ["checkout", current])
        if code != 0:
            return {"success": False, "error": f"Failed to switch back to {current}: {err}"}
        return {"success": True, "message": f"Successfully merged {current} into {branch}."}

    if action == "merge-this-into-current":
        code, out, err = run_git(target, ["merge", "--no-edit", branch])
        if code != 0:
            conflict = _is_conflict(err, out)
            if conflict:
                run_git(target, ["merge", "--abort"])
            return {"success": False, "conflict": conflict, "error": f"Merge failed: {err or out}"}
        return {"success": True, "message": f"Successfully merged {branch} into {current}."}

    if action == "rebase":
        code, out, err = run_git(target, ["rebase", branch])
        if code != 0:
            run_git(target, ["rebase", "--abort"])
            return {"success": False, "error": err or out or "Rebase failed"}
        return {"success": True, "message": f"Rebased {current} onto {branch}."}

    return {"success": False, "error": f"Invalid action: {action}"}


def handle_git_sync_all_branches(data: dict) -> Dict[str, Any]:
    target_branch = str(data.get("targetBranch") or "main").strip()
    token = str(data.get("githubToken") or "").strip()

    valid, reason = validate_ref(target_branch)
    if not valid:
        return {"success": False, "error": f"Invalid targetBranch: {reason}"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)

    job_id = create_job("git_sync_all", f"sync all repos to {target_branch}")

    def _sync():
        success_count = 0
        fail_count = 0
        for r in repos:
            append_job_log(job_id, "output", f"\n--- Syncing {r.name} ---\n")
            code, _, err = run_git(r, ["checkout", "--", target_branch])
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
