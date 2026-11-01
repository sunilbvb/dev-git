import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from devgit.core.git import (
    get_workspace_root,
    discover_git_repos,
    run_git,
    validate_ref,
    get_enhanced_env,
)

logger = logging.getLogger("devgit.scoped_branch")


def _melos_list(cwd: Path, extra: Optional[List[str]] = None) -> Tuple[bool, Any]:
    cmd = ["melos", "list", "--json"] + (extra or [])
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=120, env=get_enhanced_env(),
        )
    except FileNotFoundError:
        return False, "melos CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return False, "melos list timed out"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "melos list failed").strip()
    out = proc.stdout
    start = out.find("[")
    try:
        return True, json.loads(out[start:] if start >= 0 else out)
    except ValueError:
        return False, "Could not parse melos list output"


def _repo_for(location: Path, repos: List[Path]) -> Optional[Path]:
    best = None
    for repo in repos:
        if location == repo or repo in location.parents:
            if best is None or len(repo.parts) > len(best.parts):
                best = repo
    return best


def resolve_scope_repos(app_repo: Path, workspace_root: Path, repos: List[Path]) -> Tuple[bool, Any]:
    """App repo + every repo holding one of the app's dependent Melos packages (app first, deduped)."""
    ok, packages = _melos_list(workspace_root)
    if not ok:
        return False, packages
    app_pkg = None
    for pkg in packages:
        loc = Path(pkg.get("location", "")).resolve()
        if loc == app_repo or app_repo in loc.parents:
            app_pkg = pkg.get("name")
            break
    if not app_pkg:
        return False, f"No Melos package found inside {app_repo}"

    ok, deps = _melos_list(workspace_root, [f"--scope={app_pkg}", "--include-dependencies"])
    if not ok:
        return False, deps

    ordered: List[Path] = [app_repo]
    skipped: List[str] = []
    for pkg in deps:
        repo = _repo_for(Path(pkg.get("location", "")).resolve(), repos)
        if repo is None or repo == workspace_root:
            # Package has no repo of its own (it lives in the workspace root repo): never branch the root.
            skipped.append(pkg.get("name", "?"))
        elif repo not in ordered:
            ordered.append(repo)
    return True, {"package": app_pkg, "repos": ordered, "skippedPackages": skipped}


def _ref_exists(repo: Path, ref: str) -> bool:
    code, _, _ = run_git(repo, ["rev-parse", "--verify", "--quiet", ref])
    return code == 0


def package_branch_name(app_branch: str, app_repo: Path) -> str:
    """Packages nest the app name after the prefix: hotfix/v1.0.8/x -> hotfix/<app>/v1.0.8/x (the app keeps the plain name)."""
    app = app_repo.name.lower().replace("_", "-")
    parts = app_branch.split("/")
    if len(parts) < 2:
        return f"{app}/{app_branch}"
    if parts[1] == app:
        return app_branch
    return "/".join([parts[0], app] + parts[1:])


STANDARD_BASES = {"main", "master", "develop"}


def package_base_name(base: str, app_repo: Path) -> str:
    """Packages hold a non-standard base (e.g. a hotfix branch) under the nested name; main/master/develop are shared."""
    return base if base in STANDARD_BASES else package_branch_name(base, app_repo)


def _preflight(repo: Path, branch: str, base: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {"repo": repo.name, "path": str(repo), "branch": branch, "ok": True, "exists": False}
    code, cur, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    row["previousBranch"] = cur if code == 0 else ""
    if _ref_exists(repo, f"refs/heads/{branch}") or _ref_exists(repo, f"refs/remotes/origin/{branch}"):
        row["exists"] = True
        return row
    code, porcelain, err = run_git(repo, ["status", "--porcelain"])
    if code != 0:
        row.update(ok=False, error=f"git status failed: {err}")
    elif porcelain.strip():
        row.update(ok=False, error="Working tree has uncommitted changes")
    elif not (_ref_exists(repo, f"refs/heads/{base}") or _ref_exists(repo, f"refs/remotes/origin/{base}")):
        row.update(ok=False, error=f"Base branch '{base}' not found locally or on origin")
    return row


def _create_from_base(repo: Path, branch: str, base: str) -> Tuple[bool, str]:
    if _ref_exists(repo, f"refs/heads/{base}"):
        code, _, err = run_git(repo, ["checkout", base])
    else:
        code, _, err = run_git(repo, ["checkout", "-b", base, f"origin/{base}"])
    if code != 0:
        return False, f"checkout {base} failed: {err}"
    if _ref_exists(repo, f"refs/remotes/origin/{base}"):
        code, _, err = run_git(repo, ["pull", "--ff-only", "origin", base], timeout=60)
        if code != 0:
            return False, f"pull {base} failed: {err}"
    code, _, err = run_git(repo, ["checkout", "-b", branch])
    if code != 0:
        return False, f"create {branch} failed: {err}"
    return True, ""


def handle_git_branch_create_scoped(data: dict) -> Dict[str, Any]:
    """Create a branch from baseBranch in an app repo and every repo of its dependent Melos packages.

    branchName is the app's name; packages get package_branch_name(). Every repo is checked first and nothing
    changes unless all pass. Existing branches: reported as alreadyExists, or skipped when skipExisting is true.
    dryRun=true only returns the plan."""
    repo_path = str(data.get("repoPath") or "").strip()
    branch = str(data.get("branchName") or "").strip()
    base = str(data.get("baseBranch") or "main").strip()
    dry_run = data.get("dryRun") is True
    skip_existing = data.get("skipExisting") is True
    token = str(data.get("githubToken") or "").strip()

    if not repo_path or not branch:
        return {"success": False, "error": "Missing repoPath or branchName"}
    for label, ref in (("branchName", branch), ("baseBranch", base)):
        valid, reason = validate_ref(ref)
        if not valid:
            return {"success": False, "error": f"Invalid {label}: {reason}"}
    if branch == base:
        return {"success": False, "error": "Branch and base branch are the same"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    app_repo = Path(repo_path).resolve()
    if app_repo not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    ok, scope = resolve_scope_repos(app_repo, workspace_root, repos)
    if not ok:
        return {"success": False, "error": f"Could not resolve dependent packages: {scope}"}
    targets: List[Path] = scope["repos"]

    for repo in targets:
        code, _, err = run_git(repo, ["fetch", "origin"], timeout=60, token=token)
        if code != 0:
            return {"success": False, "error": f"Fetch failed in {repo.name}: {err}", "package": scope["package"]}

    rows = []
    for repo in targets:
        is_app = repo == app_repo
        row = _preflight(repo, branch if is_app else package_branch_name(branch, app_repo),
                         base if is_app else package_base_name(base, app_repo))
        row["base"] = base if is_app else package_base_name(base, app_repo)
        rows.append(row)
    info = {"package": scope["package"], "skippedPackages": scope.get("skippedPackages", []),
            "baseBranch": base, "repos": rows}

    existing = [r["repo"] for r in rows if r["exists"]]
    missing = [r["repo"] for r in rows if not r["exists"]]
    if existing and not skip_existing:
        return {**info, "success": False, "changed": False, "alreadyExists": True,
                "existingRepos": existing, "missingRepos": missing,
                "error": f"Branch already exists in: {', '.join(existing)}"}
    if existing and not missing:
        return {**info, "success": False, "changed": False, "alreadyExists": True,
                "existingRepos": existing, "missingRepos": [],
                "error": "Branch already exists in every repo in scope"}

    failed = [r for r in rows if not r["ok"]]
    if failed:
        return {**info, "success": False, "changed": False,
                "error": "Pre-check failed in " + ", ".join(f"{r['repo']} ({r['error']})" for r in failed)
                         + "; nothing was changed"}
    if dry_run:
        return {**info, "success": True, "changed": False, "dryRun": True,
                "message": f"Plan OK: would create the branch from '{base}' in {len(missing)} repo(s)"}

    for row, repo in zip(rows, targets):
        if row["exists"]:
            continue
        done, err = _create_from_base(repo, row["branch"], row["base"])
        row["created"] = done
        if not done:
            row.update(ok=False, error=err)
            return {**info, "success": False, "changed": True,
                    "error": f"Stopped at {repo.name}: {err}. Earlier repos keep the new branch."}
    return {**info, "success": True, "changed": True,
            "message": f"Created the branch from '{base}' in {len(missing)} repo(s)"}
