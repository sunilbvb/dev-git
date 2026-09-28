import shlex
import subprocess
import threading
import logging
from pathlib import Path
from typing import Dict, Any, List

from core.git import get_workspace_root, discover_git_repos, get_enhanced_env
from core.jobs import new_job_id, create_job, append_job_log, complete_job, get_job

logger = logging.getLogger("devgit.terminal")

ALLOWED_SUBCOMMANDS = {
    "status", "log", "diff", "branch", "checkout", "commit", "stash", 
    "pull", "fetch", "push", "tag", "add", "reset", "restore", 
    "merge", "rebase", "show", "rev-parse", "shortlog"
}

DANGEROUS_FLAGS = {
    "-c", "--config", "--exec-path", "--upload-pack", "--receive-pack",
    "--config-env", "-C", "--git-dir", "--work-tree"
}


def validate_git_terminal_args(args: List[str]) -> Tuple_Bool_Reason:
    if not args:
        return False, "Empty command"
        
    subcommand = args[0]
    if subcommand not in ALLOWED_SUBCOMMANDS:
        return False, f"Subcommand '{subcommand}' is not permitted in web terminal. Allowed: {', '.join(sorted(ALLOWED_SUBCOMMANDS))}"

    for arg in args:
        if arg in DANGEROUS_FLAGS or arg.startswith("-c=") or arg.startswith("--config=") or arg.startswith("--exec-path="):
            return False, f"Flag '{arg}' is forbidden for security reasons"
        if arg.startswith("-c") and len(arg) > 2 and not arg.startswith("--"):
            return False, f"Flag '{arg}' is forbidden for security reasons"
        # Check for shell execution vectors
        if any(char in arg for char in [";", "|", "`", "$("]):
            return False, "Command contains invalid characters"

    return True, ""


# Type alias helper for return values
Tuple_Bool_Reason = tuple[bool, str]


def start_git_terminal_job(job_id: str, repo: Path, args: List[str]) -> None:
    """
    Executes a validated git terminal command asynchronously in background thread.
    """
    def _run():
        cmd = ["git"] + args
        cmd_str = " ".join(cmd)
        append_job_log(job_id, "output", f"$ {cmd_str}\n")
        env = get_enhanced_env()

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1
            )

            def read_stream(stream, field):
                for line in iter(stream.readline, ""):
                    append_job_log(job_id, field, line)
                stream.close()

            t_out = threading.Thread(target=read_stream, args=(proc.stdout, "output"), daemon=True)
            t_err = threading.Thread(target=read_stream, args=(proc.stderr, "error"), daemon=True)
            t_out.start()
            t_err.start()

            ret = proc.wait(timeout=120)
            t_out.join()
            t_err.join()

            if ret == 0:
                complete_job(job_id, status="success")
            else:
                complete_job(job_id, status="error", error_msg=f"Process exited with code {ret}")

        except subprocess.TimeoutExpired:
            proc.kill()
            complete_job(job_id, status="error", error_msg="Terminal job timed out after 120s")
        except Exception as e:
            logger.exception("Error running terminal job")
            complete_job(job_id, status="error", error_msg=str(e))

    threading.Thread(target=_run, daemon=True).start()


def handle_git_terminal_run(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    cmd_str = str(data.get("command") or "").strip()

    if not repo_path or not cmd_str:
        return {"success": False, "error": "Missing repoPath or command"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    repo = Path(repo_path).resolve()
    if repo not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    try:
        args = shlex.split(cmd_str)
    except Exception as e:
        return {"success": False, "error": f"Parse error: {e}"}

    if not args:
        return {"success": False, "error": "Empty command"}

    if args[0] == "git":
        args = args[1:]

    if not args:
        return {"success": False, "error": "Empty git command"}

    is_valid, reason = validate_git_terminal_args(args)
    if not is_valid:
        return {"success": False, "error": f"Security restriction: {reason}"}

    job_id = create_job("git_terminal", f"git {' '.join(args)}", {"repo": str(repo)})
    start_git_terminal_job(job_id, repo, args)
    return {"success": True, "jobId": job_id}
