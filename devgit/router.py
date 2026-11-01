import sys
from pathlib import Path

DEVGIT_DIR = Path(__file__).resolve().parent
if str(DEVGIT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(DEVGIT_DIR.parent))

from devgit.core.git import (
    set_workspace_root,
    get_workspace_root,
    discover_git_repos as _discover_git_repos,
    run_git as _run_git,
    git_repo_status as _git_repo_status,
    validate_ref,
    _WORKSPACE_ROOT,
    _CACHE_FILE,
)

from devgit.core.jobs import (
    _JOBS,
    _JOBS_LOCK,
    _NEXT_JOB_ID,
    new_job_id as _new_job_id,
    append_job_log as _append_job_log,
)

from devgit.core.auth import (
    get_session_token,
    set_session_token,
    verify_token,
    is_allowed_origin_or_host,
)

from devgit.modules.branches import (
    serve_git_branches,
    handle_git_branch_create,
    handle_git_branch_delete,
    handle_git_branch_finish,
    handle_git_hotfix_create,
    handle_git_hotfix_finish,
    handle_git_branch_action,
    handle_git_sync_all_branches,
)

from devgit.modules.staging import (
    serve_git_status_files,
    handle_git_stage,
)

from devgit.modules.conflicts import (
    serve_git_conflicts_list,
    serve_git_conflict_file,
    handle_git_conflict_resolve,
    handle_git_conflict_abort,
)

from devgit.modules.graph import (
    serve_git_graph,
)

from devgit.modules.doctor import (
    serve_git_doctor,
    handle_git_doctor_fix,
)

from devgit.modules.scoped_branch import handle_git_branch_create_scoped

from devgit.modules.stash import (
    serve_git_stashes,
    handle_git_stash_create,
    handle_git_stash_apply,
    handle_git_stash_pop,
    handle_git_stash_drop,
    handle_git_stash_pull_pop,
)

from devgit.modules.release import (
    handle_git_tags_list,
    handle_git_tag_create,
    handle_git_tag_delete,
    handle_git_tag_push,
    handle_git_recommend_bump,
    handle_git_tags_compare,
    handle_git_tag_edit,
    handle_git_release_create,
)

from devgit.modules.release_all import (
    handle_git_release_all_preview,
    handle_git_release_all_run,
)

from devgit.core.workspaces import add_workspace, remove_workspace, list_workspaces

from devgit.modules.worktrees import (
    serve_git_worktrees,
    handle_git_worktree_add,
    handle_git_worktree_remove,
    handle_git_worktree_prune,
    get_repo_worktrees,
)

from devgit.modules.terminal import (
    handle_git_terminal_run,
    start_git_terminal_job as _start_git_terminal_job,
    validate_git_terminal_args,
)

from devgit.modules.ai import (
    handle_git_ai_commit_message_async,
)

from devgit.modules.commits import (
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


def serve_saved_workspaces() -> dict:
    return {"success": True, "workspaces": list_workspaces()}


def handle_workspace_save(data: dict) -> dict:
    path_str = (data.get("workspace") or data.get("path") or "").strip()
    if not path_str:
        return {"success": False, "error": "Missing workspace path"}
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        return {"success": False, "error": f"Directory does not exist: {path}"}
    try:
        add_workspace(path)
    except OSError as e:
        return {"success": False, "error": f"Could not save: {e}"}
    return serve_saved_workspaces()


def handle_workspace_remove(data: dict) -> dict:
    path_str = (data.get("workspace") or data.get("path") or "").strip()
    if not path_str:
        return {"success": False, "error": "Missing workspace path"}
    try:
        remove_workspace(path_str)
    except OSError as e:
        return {"success": False, "error": f"Could not remove: {e}"}
    return serve_saved_workspaces()


def handle_workspace_switch(data: dict) -> dict:
    new_path_str = (data.get("workspace") or data.get("workspacePath") or data.get("path") or "").strip()
    if not new_path_str:
        return {"success": False, "error": "Missing workspace path"}

    new_path = Path(new_path_str).expanduser().resolve()
    if not new_path.exists() or not new_path.is_dir():
        return {"success": False, "error": f"Directory does not exist: {new_path}"}

    set_workspace_root(new_path)
    try:
        add_workspace(new_path)
    except OSError:
        pass
    if _CACHE_FILE.exists():
        try:
            _CACHE_FILE.unlink()
        except OSError:
            pass

    return {
        "success": True,
        "message": f"Workspace switched to {new_path}",
        "workspace": str(new_path),
        "workspaceRoot": str(new_path),
        "name": new_path.name
    }


def _translate_branch_name(branch: str, app_name: str, use_melos: bool) -> str:
    if not use_melos or not app_name or app_name.lower() == "all":
        return branch
    return branch
