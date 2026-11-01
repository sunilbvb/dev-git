"""Release all repos: merge a source branch (develop) into a release branch (main), tag, and publish GitHub releases.

Never deletes branches. Preview is read-only (fetch only); run preflights every selected repo and aborts
before changing anything if one is dirty, has a merge conflict, or is missing a branch.
"""
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from devgit.core.git import (
    discover_git_repos,
    get_enhanced_env,
    get_workspace_root,
    run_git,
    validate_ref,
)
from devgit.core.jobs import _JOBS, _JOBS_LOCK, append_job_log, complete_job, create_job

_NET_TIMEOUT = 90
_DEFAULT_PACKAGE_NOTE = "Release {tags}."


def _norm(name: str) -> str:
    return name.replace("_", "-").lower()


def _tag_prefix(tag: str) -> str:
    match = re.match(r"^(.+?)-v?\d", tag)
    return _norm(match.group(1)) if match else ""


def _release_tag_for(repo: Path, tags: List[str]) -> Tuple[str, bool]:
    """Pick the tag a repo's GitHub release is for. A tag named after the repo (gyo_business ->
    gyo-business-v1.0.7+164) is the repo's own tag and gets the full notes; other repos use the first tag."""
    for tag in tags:
        if _tag_prefix(tag) == _norm(repo.name):
            return tag, True
    return tags[0], False


def _tags_for_repo(repo: Path, tags: List[str], tag_map: Dict[str, List[str]]) -> List[str]:
    """Tags a repo receives. An explicit tagMap entry wins. Otherwise an app repo (under apps/) gets only the
    tags named after it, falling back to all tags when none match; every other repo (packages) gets all tags."""
    if repo.name in tag_map:
        return tag_map[repo.name]
    if repo.parent.name == "apps":
        own = [t for t in tags if _tag_prefix(t) == _norm(repo.name)]
        if own:
            return own
    return tags


def _clean_tags(raw: Any) -> List[str]:
    return [str(t).strip() for t in (raw or []) if str(t).strip()]


def _parse_tags(data: dict) -> Tuple[List[str], Dict[str, List[str]], Optional[Dict[str, Any]]]:
    tags = _clean_tags(data.get("tags"))
    tag_map = {str(k): _clean_tags(v) for k, v in (data.get("tagMap") or {}).items()}
    for tag in tags + [t for v in tag_map.values() for t in v]:
        valid, reason = validate_ref(tag)
        if not valid:
            return [], {}, {"success": False, "error": f"Invalid tag '{tag}': {reason}"}
    return tags, tag_map, None


def _ref_exists(repo: Path, ref: str) -> bool:
    return run_git(repo, ["rev-parse", "-q", "--verify", ref])[0] == 0


def _count(repo: Path, left: str, right: str) -> Tuple[int, int]:
    code, out, _ = run_git(repo, ["rev-list", "--left-right", "--count", f"{left}...{right}"])
    if code != 0:
        return 0, 0
    parts = out.split()
    return int(parts[0]), int(parts[1])


def _plan_repo(repo: Path, source: str, dest: str, token: str, fetch: bool = True) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "repoPath": str(repo),
        "repoName": repo.name,
        "strategy": "error",
        "ok": False,
        "behind": 0,
        "ahead": 0,
        "warnings": [],
    }
    if fetch:
        code, _, err = run_git(repo, ["fetch", "--prune", "origin"], timeout=_NET_TIMEOUT, token=token)
        if code != 0:
            plan["reason"] = f"fetch failed: {err}"
            return plan

    plan["currentBranch"] = run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])[1]
    if not _ref_exists(repo, f"refs/remotes/origin/{source}"):
        plan["reason"] = f"origin/{source} not found"
        plan["strategy"] = "missing-branch"
        return plan
    if not _ref_exists(repo, f"refs/remotes/origin/{dest}"):
        plan["reason"] = f"origin/{dest} not found"
        plan["strategy"] = "missing-branch"
        return plan

    if run_git(repo, ["status", "--porcelain"])[1]:
        plan["reason"] = "working tree has uncommitted changes"
        plan["strategy"] = "dirty"
        return plan

    if _ref_exists(repo, f"refs/heads/{source}"):
        _, unpushed = _count(repo, f"origin/{source}", source)
        if unpushed:
            plan["reason"] = f"local {source} has {unpushed} unpushed commit(s); push or reset first"
            plan["strategy"] = "unpushed"
            return plan

    behind, ahead = _count(repo, f"origin/{dest}", f"origin/{source}")
    plan["behind"], plan["ahead"] = behind, ahead
    if ahead == 0:
        plan["strategy"] = "up-to-date"
        plan["ok"] = True
        return plan
    if behind == 0:
        plan["strategy"] = "fast-forward"
        plan["ok"] = True
        return plan

    code, out, err = run_git(repo, ["merge-tree", "--write-tree", f"origin/{dest}", f"origin/{source}"])
    if code == 0:
        plan["strategy"] = "merge"
        plan["ok"] = True
    elif code == 1:
        plan["strategy"] = "conflict"
        plan["reason"] = "merge would conflict"
    else:
        plan["strategy"] = "merge"
        plan["ok"] = True
        plan["warnings"].append("could not pre-check conflicts (git too old?); merge aborts safely if one occurs")
    return plan


def _parse_common(data: dict) -> Tuple[Optional[dict], Optional[Dict[str, Any]]]:
    source = str(data.get("sourceBranch") or "develop").strip()
    dest = str(data.get("releaseBranch") or "main").strip()
    for label, ref in (("sourceBranch", source), ("releaseBranch", dest)):
        valid, reason = validate_ref(ref)
        if not valid:
            return None, {"success": False, "error": f"Invalid {label}: {reason}"}
    if source == dest:
        return None, {"success": False, "error": "sourceBranch and releaseBranch are the same"}

    known = discover_git_repos(get_workspace_root())
    requested = data.get("repoPaths")
    repos: List[Path] = []
    if requested:
        for rp in requested:
            target = Path(str(rp)).resolve()
            if target not in known:
                return None, {"success": False, "error": f"Unknown repoPath: {rp}"}
            repos.append(target)
    else:
        repos = list(known)
    return {
        "source": source,
        "dest": dest,
        "repos": repos,
        "token": str(data.get("githubToken") or "").strip(),
    }, None


def handle_git_release_all_preview(data: dict) -> Dict[str, Any]:
    """Read-only: fetch and report what Release All would do per repo."""
    common, error = _parse_common(data)
    if error:
        return error
    tags, tag_map, tag_error = _parse_tags(data)
    if tag_error:
        return tag_error
    plans = [_plan_repo(r, common["source"], common["dest"], common["token"]) for r in common["repos"]]
    for repo, plan in zip(common["repos"], plans):
        plan["tags"] = _tags_for_repo(repo, tags, tag_map)
    return {"success": True, "sourceBranch": common["source"], "releaseBranch": common["dest"], "repos": plans}


def _gh(repo: Path, args: List[str], token: str) -> Tuple[int, str, str]:
    extra = {"GH_TOKEN": token, "GITHUB_TOKEN": token} if token else None
    try:
        proc = subprocess.run(
            ["gh", *args],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_NET_TIMEOUT,
            env=get_enhanced_env(extra),
        )
        return proc.returncode, proc.stdout.strip(), (proc.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "gh CLI not found; install GitHub CLI and run `gh auth login`"
    except subprocess.TimeoutExpired:
        return 1, "", f"gh timed out after {_NET_TIMEOUT}s"


def _merge_push(repo: Path, plan: dict, source: str, dest: str, token: str, step, message: str) -> None:
    """Check out dest, bring it level with origin, merge origin/source per the plan, push dest."""
    if _ref_exists(repo, f"refs/heads/{dest}"):
        code, _, err = run_git(repo, ["checkout", dest])
    else:
        code, _, err = run_git(repo, ["checkout", "-b", dest, f"origin/{dest}"])
    if code != 0:
        raise RuntimeError(f"checkout {dest} failed: {err}")
    code, _, err = run_git(repo, ["merge", "--ff-only", f"origin/{dest}"])
    if code != 0:
        raise RuntimeError(f"local {dest} cannot fast-forward to origin/{dest}: {err}")

    if plan["strategy"] == "fast-forward":
        code, _, err = run_git(repo, ["merge", "--ff-only", f"origin/{source}"])
        if code != 0:
            raise RuntimeError(f"fast-forward failed: {err}")
        step(f"fast-forwarded {dest} to {source}")
    elif plan["strategy"] == "merge":
        code, out, err = run_git(repo, ["merge", "--no-ff", "-m", message, f"origin/{source}"])
        if code != 0:
            run_git(repo, ["merge", "--abort"])
            raise RuntimeError(f"merge failed (aborted): {err or out}")
        step(f"merged {source} into {dest}")
    else:
        step(f"{dest} already contains {source}")

    code, _, err = run_git(repo, ["push", "origin", dest], timeout=_NET_TIMEOUT, token=token)
    if code != 0:
        raise RuntimeError(f"push {dest} failed: {err}")
    step(f"pushed {dest}")


def _release_repo(repo: Path, plan: dict, opts: dict, log) -> Dict[str, Any]:
    """Merge, push, tag and release one repo. Raises RuntimeError on failure; always restores the branch."""
    source, dest, token = opts["source"], opts["dest"], opts["token"]
    tags: List[str] = _tags_for_repo(repo, opts["tags"], opts["tagMap"])
    original = plan.get("currentBranch") or source
    result: Dict[str, Any] = {"repoName": repo.name, "repoPath": str(repo), "strategy": plan["strategy"], "steps": []}

    def step(msg: str) -> None:
        result["steps"].append(msg)
        log(f"  {repo.name}: {msg}\n")

    try:
        _merge_push(repo, plan, source, dest, token, step,
                    f"Merge branch '{source}' into {dest}" + (" (back-merge)" if opts["mode"] == "sync" else " for release"))
        if opts["mode"] == "sync":
            return result

        for tag in tags:
            if _ref_exists(repo, f"refs/tags/{tag}"):
                step(f"tag {tag} already exists locally; kept")
            else:
                code, out, err = run_git(repo, ["tag", "-a", tag, dest, "-m", opts["notes"] or f"Release {tag}"])
                if code != 0:
                    raise RuntimeError(f"tag {tag} failed: {err or out}")
                step(f"created tag {tag}")
            code, _, err = run_git(repo, ["push", "origin", "--", f"refs/tags/{tag}"], timeout=_NET_TIMEOUT, token=token)
            if code != 0:
                raise RuntimeError(f"push tag {tag} failed: {err}")
        if tags:
            step(f"pushed tags: {', '.join(tags)}")

        if opts["githubReleases"] and tags:
            tag, own = _release_tag_for(repo, tags)
            body = opts["notes"] if own else opts["packageNote"].replace("{tags}", " and ".join(tags))
            if _gh(repo, ["release", "view", tag], token)[0] == 0:
                step(f"GitHub release {tag} already exists; kept")
            else:
                code, out, err = _gh(
                    repo, ["release", "create", tag, "--verify-tag", "--title", tag, "--notes", body or f"Release {tag}"], token
                )
                if code != 0:
                    raise RuntimeError(f"GitHub release {tag} failed: {err or out}")
                step(f"GitHub release {tag}: {out}")

        if opts["backMerge"]:
            back = _plan_repo(repo, dest, source, token, fetch=False)
            if not back["ok"]:
                raise RuntimeError(f"back-merge {dest} into {source} blocked: {back.get('reason') or back['strategy']}")
            _merge_push(repo, back, dest, source, token, step, f"Merge branch '{dest}' into {source} (back-merge)")
    finally:
        if original and original != dest:
            run_git(repo, ["checkout", original])
    return result


def _run_release_all(job_id: str, opts: dict) -> None:
    log = lambda text: append_job_log(job_id, "output", text)
    results: List[Dict[str, Any]] = []
    try:
        log("Preflight (fetch + checks)...\n")
        plans = [_plan_repo(r, opts["source"], opts["dest"], opts["token"]) for r in opts["repos"]]
        bad = [p for p in plans if not p["ok"]]
        for p in plans:
            log(f"  {p['repoName']}: {p['strategy']}" + (f" ({p['reason']})" if p.get("reason") else "") + "\n")
        if bad:
            raise RuntimeError(f"Preflight failed for {len(bad)} repo(s); nothing was changed.")

        log("Releasing...\n")
        failed = None
        for repo, plan in zip(opts["repos"], plans):
            if failed:
                results.append({"repoName": repo.name, "strategy": "skipped"})
                continue
            try:
                results.append(_release_repo(repo, plan, opts, log))
                log(f"OK {repo.name}\n")
            except RuntimeError as exc:
                failed = f"{repo.name}: {exc}"
                results.append({"repoName": repo.name, "strategy": "failed", "error": str(exc)})
                log(f"FAILED {failed}\n")
        with _JOBS_LOCK:
            if job_id in _JOBS:
                _JOBS[job_id]["results"] = results
        if failed:
            raise RuntimeError(f"Stopped at {failed}. Remaining repos were skipped; fix and re-run (safe to repeat).")
        complete_job(job_id, "success")
        log(f"Done: {len(results)} repo(s) released.\n")
    except Exception as exc:  # noqa: BLE001 - surface any failure on the job
        with _JOBS_LOCK:
            if job_id in _JOBS:
                _JOBS[job_id].setdefault("results", results)
        complete_job(job_id, "error", str(exc))


def handle_git_release_all_run(data: dict) -> Dict[str, Any]:
    common, error = _parse_common(data)
    if error:
        return error
    if not data.get("repoPaths"):
        return {"success": False, "error": "repoPaths is required to run a release (use preview to pick repos)"}

    tags, tag_map, tag_error = _parse_tags(data)
    if tag_error:
        return tag_error

    opts = {
        **common,
        "tags": tags,
        "tagMap": tag_map,
        "notes": str(data.get("notes") or "").strip(),
        "packageNote": str(data.get("packageNote") or _DEFAULT_PACKAGE_NOTE).strip(),
        "githubReleases": bool(data.get("githubReleases", False)),
        "mode": "sync" if data.get("mode") == "sync" else "release",
        "backMerge": bool(data.get("backMerge", False)),
    }
    if opts["mode"] == "sync":
        opts["githubReleases"] = False
        opts["backMerge"] = False
        opts["tags"], opts["tagMap"] = [], {}
    if opts["githubReleases"] and not any(_tags_for_repo(r, tags, tag_map) for r in common["repos"]):
        return {"success": False, "error": "GitHub releases need at least one tag"}

    job_id = create_job("release-all", f"{opts['mode']} {common['source']} -> {common['dest']}", {"results": []})
    threading.Thread(target=_run_release_all, args=(job_id, opts), daemon=True).start()
    return {"success": True, "jobId": job_id}
