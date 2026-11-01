import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
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

    token = str(data.get("githubToken") or "").strip()

    remote_tags = set()
    code_r, out_r, _ = run_git(target, ["ls-remote", "--tags", "origin"], timeout=10, token=token)
    if code_r == 0:
        for line in out_r.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                name = parts[1][len("refs/tags/"):]
                remote_tags.add(name[:-3] if name.endswith("^{}") else name)

    # \x1f / \x1e separate fields/records because %(contents) is multi-line and may contain "|".
    code, out, err = run_git(
        target,
        ["for-each-ref", "--format=%(refname:short)%1f%(contents)%1f%(objectname)%1f%(creatordate:unix)%1e", "refs/tags"],
        timeout=10,
    )
    if code != 0:
        return {"success": False, "error": err or "Failed to list tags"}

    tags = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split("\x1f")
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        message = parts[1].strip() or name
        sha = parts[2].strip()[:8]
        ts_str = parts[3].strip() if len(parts) > 3 else ""
        timestamp = int(ts_str) if ts_str.isdigit() else 0
        pushed = name in remote_tags
        tags.append({
            "name": name,
            "version": name,
            "message": message,
            "timestamp": timestamp,
            "pushed": pushed,
            "repos": [{
                "repoName": target.name,
                "repoPath": str(target),
                "tagName": name,
                "pushed": pushed,
                "sha": sha,
                "message": message,
            }],
        })
    tags.sort(key=lambda t: t["timestamp"], reverse=True)

    return {"success": True, "tags": tags, "isMelos": False, "repo": str(target)}


def _get_pubspec_version(repo_dir: Path) -> Optional[str]:
    pubspec = repo_dir / "pubspec.yaml"
    try:
        match = re.search(r"^version:\s*([^\s#]+)", pubspec.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        return None
    return match.group(1).strip() if match else None


def _tag_one(repo: Path, tag_name: str, message: str, push: bool, token: str) -> Dict[str, Any]:
    """Create (and optionally push) one annotated tag in a repo; an existing tag is skipped, never moved."""
    row: Dict[str, Any] = {"repo": repo.name, "path": str(repo), "tagName": tag_name,
                           "created": False, "skipped": False, "pushed": False}
    if run_git(repo, ["rev-parse", "-q", "--verify", f"refs/tags/{tag_name}"])[0] == 0:
        row["skipped"] = True
        return row
    code, out, err = run_git(repo, ["tag", "-a", tag_name, "-m", message or f"Release {tag_name}"])
    if code != 0:
        row["error"] = f"Failed to create tag: {err or out}"
        return row
    row["created"] = True
    if push:
        code, _, err = run_git(repo, ["push", "origin", "--", f"refs/tags/{tag_name}"], timeout=30, token=token)
        if code != 0:
            row["error"] = f"Tag created locally, but failed to push to origin: {err}"
            return row
        row["pushed"] = True
    return row


def handle_git_tag_create(data: dict) -> Dict[str, Any]:
    """Create an annotated release tag. A blank name falls back to the pubspec version, then 1.0.0.

    useMelos=true tags the app repo as v<ver> and every repo of its dependent Melos packages as
    <app-slug>-v<ver> (same nesting as scoped branches). Existing tags are skipped. dryRun=true returns the plan."""
    raw_name = str(data.get("tagName") or data.get("tag") or "").strip()
    message = str(data.get("message") or "").strip()
    push_to_remote = bool(data.get("pushToRemote", False))
    use_melos = data.get("useMelos") is True
    dry_run = data.get("dryRun") is True
    token = str(data.get("githubToken") or "").strip()

    target, error = _resolve_repo(data)
    if error:
        return error

    base_version = raw_name or _get_pubspec_version(target) or "1.0.0"
    tag_name = base_version if base_version.startswith("v") else f"v{base_version}"
    valid, reason = validate_ref(tag_name)
    if not valid:
        return {"success": False, "error": f"Invalid tagName: {reason}"}

    if not use_melos:
        row = _tag_one(target, tag_name, message, push_to_remote, token)
        if row.get("error"):
            return {"success": False, "error": row["error"]}
        if row["skipped"]:
            return {"success": True, "message": f"Tag '{tag_name}' already exists on {target.name}.", "skipped": True}
        return {
            "success": True,
            "message": f"Tag '{tag_name}' created {'and pushed to remote' if row['pushed'] else 'locally'}.",
            "tagName": tag_name,
            "pushed": row["pushed"],
        }

    from devgit.modules.scoped_branch import resolve_scope_repos

    workspace_root = get_workspace_root()
    ok, scope = resolve_scope_repos(target, workspace_root, discover_git_repos(workspace_root))
    if not ok:
        return {"success": False, "error": f"Could not resolve dependent packages: {scope}"}

    slug = target.name.lower().replace("_", "-")
    pkg_prefix = f"{slug}-"
    plan = [(repo, tag_name if repo == target else f"{pkg_prefix}{tag_name}") for repo in scope["repos"]]
    for _, name in plan:
        valid, reason = validate_ref(name)
        if not valid:
            return {"success": False, "error": f"Invalid tag name '{name}': {reason}"}

    info = {"package": scope["package"], "skippedPackages": scope.get("skippedPackages", []),
            "appTagName": tag_name, "pkgTagPrefix": pkg_prefix}
    if dry_run:
        rows = [{"repo": r.name, "path": str(r), "tagName": n,
                 "exists": run_git(r, ["rev-parse", "-q", "--verify", f"refs/tags/{n}"])[0] == 0} for r, n in plan]
        return {**info, "success": True, "changed": False, "dryRun": True, "repos": rows,
                "message": f"Plan OK: would tag {sum(not r['exists'] for r in rows)} of {len(rows)} repo(s)"}

    rows = []
    for repo, name in plan:
        row = _tag_one(repo, name, message, push_to_remote, token)
        rows.append(row)
        if row.get("error"):
            return {**info, "success": False, "changed": any(r["created"] for r in rows), "repos": rows,
                    "error": f"Stopped at {repo.name}: {row['error']}. Earlier repos keep their tags."}

    created = [r for r in rows if r["created"]]
    skipped = [r for r in rows if r["skipped"]]
    pushed = push_to_remote and bool(created)
    return {**info, "success": True, "changed": bool(created), "repos": rows,
            "createdCount": len(created), "skippedCount": len(skipped),
            "tagName": tag_name, "pushed": pushed, "pushedToRemote": pushed,
            "message": f"Tagged {len(created)} repo(s) {'and pushed' if pushed else 'locally'}; "
                       f"{len(skipped)} already had the tag."}


def _resolve_repo(data: dict):
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return None, {"success": False, "error": "Missing repoPath"}
    target = Path(repo_path).resolve()
    if target not in discover_git_repos(get_workspace_root()):
        return None, {"success": False, "error": "Unknown repoPath"}
    return target, None


def _resolve_tag(target: Path, version: str) -> Optional[str]:
    """Match a UI version to an existing tag: exact name first, then with a 'v' prefix."""
    for candidate in (version, f"v{version}"):
        code, _, _ = run_git(target, ["rev-parse", "-q", "--verify", f"refs/tags/{candidate}"])
        if code == 0:
            return candidate
    return None


def handle_git_tag_delete(data: dict) -> Dict[str, Any]:
    version = str(data.get("version") or data.get("tagName") or "").strip()
    if not version:
        return {"success": False, "error": "Missing parameters"}
    valid, reason = validate_ref(version)
    if not valid:
        return {"success": False, "error": f"Invalid version: {reason}"}

    target, error = _resolve_repo(data)
    if error:
        return error

    tag = _resolve_tag(target, version)
    if tag is None:
        return {"success": False, "error": f"Tag '{version}' not found"}
    code, _, err = run_git(target, ["tag", "-d", tag])
    if code != 0:
        return {"success": False, "error": err or "Failed to delete tag"}
    return {"success": True, "message": f"Successfully deleted local tag '{tag}'."}


def handle_git_tag_push(data: dict) -> Dict[str, Any]:
    """Push one tag (version/tagName given) or all tags (none given) to origin."""
    version = str(data.get("version") or data.get("tagName") or "").strip()
    token = str(data.get("githubToken") or "").strip()

    target, error = _resolve_repo(data)
    if error:
        return error

    if version:
        valid, reason = validate_ref(version)
        if not valid:
            return {"success": False, "error": f"Invalid version: {reason}"}
        tag = _resolve_tag(target, version)
        if tag is None:
            return {"success": False, "error": f"Tag '{version}' not found"}
        args = ["push", "origin", "--", f"refs/tags/{tag}"]
    else:
        args = ["push", "origin", "--tags"]

    code, out, err = run_git(target, args, timeout=30, token=token)
    if code != 0:
        return {"success": False, "error": f"Failed to push tags: {err or out}"}
    return {"success": True, "message": f"Successfully pushed tags for {target.name} to remote origin."}


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
    """Rename a local tag and/or change its message (same commit, new annotated tag)."""
    old_version = str(data.get("oldVersion") or "").strip()
    new_version = str(data.get("newVersion") or "").strip()
    message = str(data.get("message") or "").strip()
    if not old_version or not new_version or not message:
        return {"success": False, "error": "Missing parameters"}
    for label, ref in (("oldVersion", old_version), ("newVersion", new_version)):
        valid, reason = validate_ref(ref)
        if not valid:
            return {"success": False, "error": f"Invalid {label}: {reason}"}

    target, error = _resolve_repo(data)
    if error:
        return error

    old_tag = _resolve_tag(target, old_version)
    if old_tag is None:
        return {"success": False, "error": f"Tag '{old_version}' not found"}
    new_tag = new_version
    if old_tag.startswith("v") and not new_tag.startswith("v"):
        new_tag = f"v{new_tag}"

    if new_tag == old_tag:
        code, _, err = run_git(target, ["tag", "-f", "-a", new_tag, f"{old_tag}^{{}}", "-m", message])
        if code != 0:
            return {"success": False, "error": err or "Failed to update tag"}
        return {"success": True, "message": f"Updated message of tag '{new_tag}'."}

    if run_git(target, ["rev-parse", "-q", "--verify", f"refs/tags/{new_tag}"])[0] == 0:
        return {"success": False, "error": f"Tag '{new_tag}' already exists"}
    code, _, err = run_git(target, ["tag", "-a", new_tag, f"{old_tag}^{{}}", "-m", message])
    if code != 0:
        return {"success": False, "error": err or "Failed to create tag"}
    run_git(target, ["tag", "-d", old_tag])
    return {"success": True, "message": f"Successfully renamed local tag to {new_tag}."}


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
