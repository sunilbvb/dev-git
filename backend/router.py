"""
DevGit Router Facade Module
Cleanly delegates API requests to specialized domain modules.
"""

import sys
from pathlib import Path

# Ensure backend package modules can be resolved cleanly
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Core imports & re-exports for backwards compatibility
from core.git import (
    set_workspace_root,
    get_workspace_root,
    discover_git_repos as _discover_git_repos,
    run_git as _run_git,
    git_repo_status as _git_repo_status,
    _WORKSPACE_ROOT,
    _CACHE_FILE,
)

from core.jobs import (
    _JOBS,
    _JOBS_LOCK,
    _NEXT_JOB_ID,
    new_job_id as _new_job_id,
    append_job_log as _append_job_log,
)

from core.auth import (
    get_session_token,
    set_session_token,
    verify_token,
    is_allowed_origin_or_host,
)

# Feature Module Imports & Re-exports
from modules.branches import (
    serve_git_branches,
    handle_git_branch_create,
    handle_git_branch_delete,
    handle_git_branch_action,
    handle_git_sync_all_branches,
)

from modules.stash import (
    serve_git_stashes,
    handle_git_stash_create,
    handle_git_stash_apply,
    handle_git_stash_pop,
    handle_git_stash_drop,
    handle_git_stash_pull_pop,
)

from modules.release import (
    handle_git_tags_list,
    handle_git_tag_create,
    handle_git_tag_delete,
    handle_git_tag_push,
    handle_git_recommend_bump,
    handle_git_tags_compare,
    handle_git_tag_edit,
    handle_git_release_create,
)

from modules.terminal import (
    handle_git_terminal_run,
    start_git_terminal_job as _start_git_terminal_job,
    validate_git_terminal_args,
)

from modules.ai import (
    handle_git_ai_commit_message_async,
)

from modules.commits import (
    serve_git_repos,
    serve_git_user,
    serve_git_status,
    serve_git_changes,
    serve_git_diff,
    serve_git_commits,
    serve_git_branch_ci_status,
    serve_git_conflicts,
    handle_git_commit_async,
    handle_git_fetch,
    handle_git_pull,
    handle_git_push,
    handle_git_conflict_resolve,
    handle_git_contributors,
)


def handle_workspace_switch(data: dict) -> dict:
    new_path_str = (data.get("workspace") or data.get("workspacePath") or data.get("path") or "").strip()
    if not new_path_str:
        return {"success": False, "error": "Missing workspace path"}

    new_path = Path(new_path_str).expanduser().resolve()
    if not new_path.exists() or not new_path.is_dir():
        return {"success": False, "error": f"Directory does not exist: {new_path}"}

    home = Path.home().resolve()
    current_root = get_workspace_root().resolve()
    allowed_roots = [home, current_root]
    if not any(new_path == r or r in new_path.parents for r in allowed_roots):
        return {"success": False, "error": f"Workspace directory must be within $HOME ({home})"}

    set_workspace_root(new_path)
    if _CACHE_FILE.exists():
        try:
            _CACHE_FILE.unlink()
        except OSError:
            pass

    return {
        "success": True,
        "message": f"Workspace switched to {new_path}",
        "workspaceRoot": str(new_path),
        "name": new_path.name
    }


def _translate_branch_name(branch: str, app_name: str, use_melos: bool) -> str:
    if not use_melos or not app_name or app_name.lower() == "all":
        return branch
    return branch
