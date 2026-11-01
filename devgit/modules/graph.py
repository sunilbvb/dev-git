import logging
from pathlib import Path
from typing import Dict, Any, List
from urllib.parse import urlparse, parse_qs

from devgit.core.git import get_workspace_root, discover_git_repos, run_git

logger = logging.getLogger("devgit.graph")


def serve_git_graph(path_str: str) -> Dict[str, Any]:
    """Return topological Git DAG commit nodes and branch references for visual rendering."""
    parsed = urlparse(path_str)
    query = parse_qs(parsed.query)
    repo_path = (query.get("repoPath") or [""])[0].strip()
    try:
        limit = max(1, min(int((query.get("limit") or ["50"])[0]), 200))
    except ValueError:
        limit = 50

    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    cmd = [
        "log",
        f"-n{limit}",
        "--topo-order",
        "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%ad%x1f%s%x1f%D",
        "--date=relative",
    ]
    code, out, err = run_git(target, cmd, timeout=15)
    if code != 0:
        return {"success": False, "error": err or "Failed to read git log graph"}

    commits: List[Dict[str, Any]] = []
    active_lanes: List[str] = []

    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) < 6:
            continue

        commit_hash = parts[0].strip()
        parents = [p for p in parts[1].strip().split() if p]
        author = parts[2].strip()
        email = parts[3].strip()
        date_str = parts[4].strip()
        subject = parts[5].strip()
        ref_names = parts[6].strip() if len(parts) > 6 else ""

        refs_list: List[Dict[str, str]] = []
        is_head = False
        if ref_names:
            for r in ref_names.split(","):
                r = r.strip()
                if not r:
                    continue
                if r.startswith("HEAD -> "):
                    is_head = True
                    refs_list.append({"type": "head", "name": r[len("HEAD -> "):]})
                elif r == "HEAD":
                    is_head = True
                    refs_list.append({"type": "head", "name": "HEAD"})
                elif r.startswith("tag: "):
                    refs_list.append({"type": "tag", "name": r[len("tag: "):]})
                elif r.startswith("origin/"):
                    refs_list.append({"type": "remote", "name": r})
                else:
                    refs_list.append({"type": "branch", "name": r})

        # Simple lane assignment algorithm for DAG rendering
        if commit_hash in active_lanes:
            lane = active_lanes.index(commit_hash)
        else:
            lane = len(active_lanes)
            active_lanes.append(commit_hash)

        # Update lanes with parents
        if parents:
            active_lanes[lane] = parents[0]
            for extra_parent in parents[1:]:
                if extra_parent not in active_lanes:
                    active_lanes.append(extra_parent)
        else:
            active_lanes[lane] = None

        while active_lanes and active_lanes[-1] is None:
            active_lanes.pop()

        commits.append({
            "hash": commit_hash,
            "shortHash": commit_hash[:7],
            "parents": parents,
            "author": author,
            "email": email,
            "date": date_str,
            "subject": subject,
            "refs": refs_list,
            "isHead": is_head,
            "lane": lane
        })

    return {
        "success": True,
        "repo": str(target),
        "commits": commits,
        "count": len(commits)
    }
