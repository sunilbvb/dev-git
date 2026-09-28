import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import devgit.router as _devgit_router
from devgit.router import *

_discover_git_repos = _devgit_router._discover_git_repos
_git_repo_status = _devgit_router._git_repo_status
_run_git = _devgit_router._run_git
_translate_branch_name = _devgit_router._translate_branch_name
_JOBS = _devgit_router._JOBS
_JOBS_LOCK = _devgit_router._JOBS_LOCK
_WORKSPACE_ROOT = _devgit_router._WORKSPACE_ROOT
_CACHE_FILE = _devgit_router._CACHE_FILE
