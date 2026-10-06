#!/usr/bin/env python3
import http.server
import json
import logging
import os
import socketserver
import sys
import urllib.parse
from pathlib import Path

# Package-relative or standalone imports
try:
    from devgit import router
except ImportError:
    import router

logging.basicConfig(level=logging.INFO, format="[DevGit] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("devgit.server")

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGE_DIR.parent if (PACKAGE_DIR.parent / "frontend").exists() else PACKAGE_DIR

FRONTEND_DIR = PACKAGE_DIR / "frontend"
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = ROOT_DIR / "frontend"

WORKSPACE_ASSETS_DIR = ROOT_DIR / "workspace_assets"

PORT = 8086
HOST = "127.0.0.1"
MAX_PAYLOAD_BYTES = 1_048_576  # 1 MB


def _check_host_and_origin(handler) -> bool:
    host = handler.headers.get("Host")
    origin = handler.headers.get("Origin")
    if not router.is_allowed_origin_or_host(host, origin):
        handler.send_error(403, "Forbidden: Invalid Host or Origin header")
        return False
    return True


def _check_api_auth(handler) -> bool:
    parsed = urllib.parse.urlparse(handler.path)
    query = urllib.parse.parse_qs(parsed.query)
    token = handler.headers.get("X-DevGit-Token") or (query.get("token") or [""])[0]
    if not router.verify_token(token):
        _write_json(handler, {"success": False, "error": "Unauthorized: Missing or invalid token"}, status=401)
        return False
    return True


def _serve_static(handler):
    if not _check_host_and_origin(handler):
        return

    parsed = urllib.parse.urlparse(handler.path)
    relative = parsed.path.lstrip("/") or "index.html"
    
    # Fix Item #4: Require auth token for workspace_assets/
    if relative.startswith("workspace_assets/"):
        if not _check_api_auth(handler):
            return
        target = (ROOT_DIR / relative).resolve()
        base_dir = ROOT_DIR
    else:
        target = (FRONTEND_DIR / relative).resolve()
        base_dir = FRONTEND_DIR

    if target != base_dir and base_dir not in target.parents:
        handler.send_error(403, "Forbidden")
        return
    if not target.exists() or not target.is_file():
        handler.send_error(404, "Not Found")
        return

    ctype = "text/html; charset=utf-8"
    if target.suffix == ".css":
        ctype = "text/css; charset=utf-8"
    elif target.suffix == ".js":
        ctype = "application/javascript; charset=utf-8"
    elif target.suffix == ".png":
        ctype = "image/png"
    elif target.suffix in (".jpg", ".jpeg"):
        ctype = "image/jpeg"
    elif target.suffix == ".svg":
        ctype = "image/svg+xml"
    elif target.suffix == ".json":
        ctype = "application/json; charset=utf-8"

    body = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "no-store")

    origin = handler.headers.get("Origin")
    if origin and router.is_allowed_origin_or_host(handler.headers.get("Host"), origin):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Access-Control-Allow-Headers", "X-DevGit-Token, Content-Type")

    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _write_json(handler, data: dict, status: int = 200):
    payload = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-type", "application/json; charset=utf-8")
    
    origin = handler.headers.get("Origin")
    if origin and router.is_allowed_origin_or_host(handler.headers.get("Host"), origin):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Access-Control-Allow-Headers", "X-DevGit-Token, Content-Type")

    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _safe_read_json(handler):
    # Fix Item #9: Safe Content-Length parsing & 1 MB payload size limit
    try:
        content_length = int(handler.headers.get("Content-Length", 0))
    except (ValueError, TypeError):
        content_length = 0

    if content_length > MAX_PAYLOAD_BYTES:
        _write_json(handler, {"success": False, "error": "Payload Too Large (max 1 MB)"}, status=413)
        return None

    raw = handler.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _serve_job(handler):
    parsed = urllib.parse.urlparse(handler.path)
    query = urllib.parse.parse_qs(parsed.query)
    job_id = (query.get("id") or [""])[0]
    if not job_id:
        _write_json(handler, {"success": False, "error": "Missing job id"}, status=400)
        return

    with router._JOBS_LOCK:
        job = router._JOBS.get(str(job_id))
        if job is None:
            _write_json(handler, {"success": False, "error": "Job not found"}, status=404)
            return
        payload = {k: v for k, v in job.items() if k not in {"process", "pgid"}}

    _write_json(handler, {"success": True, "job": payload})


def _handle_job_stop(handler, data: dict):
    job_id = str(data.get("jobId") or data.get("id") or "").strip()
    if not job_id:
        _write_json(handler, {"success": False, "error": "Missing jobId"}, status=400)
        return

    with router._JOBS_LOCK:
        job = router._JOBS.get(job_id)
        if job is None:
            _write_json(handler, {"success": False, "error": "Job not found"}, status=404)
            return
        if job.get("status") == "running":
            job["status"] = "stopping"
            job["error"] = ((job.get("error") or "") + "\nStop requested by user.\n").strip() + "\n"

    _write_json(handler, {"success": True, "message": "Stop requested", "jobId": job_id})


def _serve_workspace(handler):
    _write_json(handler, {
        "success": True,
        "workspace": str(router.get_workspace_root()),
        "name": router.get_workspace_root().name
    })


def _handle_workspace_switch(handler, data: dict):
    _write_json(handler, router.handle_workspace_switch(data))


def _serve_apps_config(handler):
    config_file = WORKSPACE_ASSETS_DIR / "apps_config.json"
    if not config_file.exists():
        config_file = WORKSPACE_ASSETS_DIR / "apps_config.example.json"
    if not config_file.exists():
        _write_json(handler, {"success": True, "apps": []})
        return
    try:
        apps = json.loads(config_file.read_text(encoding="utf-8"))
        if not isinstance(apps, list):
            apps = []
        _write_json(handler, {"success": True, "apps": apps})
    except Exception as e:
        _write_json(handler, {"success": False, "apps": [], "error": str(e)}, status=500)


def _serve_api_not_found(handler):
    _write_json(handler, {"success": False, "error": f"Unknown API route: {handler.path}"}, status=404)


class GitHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        if not _check_host_and_origin(self):
            return
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin and router.is_allowed_origin_or_host(self.headers.get("Host"), origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "X-DevGit-Token, Content-Type")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not _check_host_and_origin(self):
            return

        if self.path.startswith("/api/"):
            if not _check_api_auth(self):
                return
            if self.path.startswith("/api/git/repos"):
                _write_json(self, router.serve_git_repos(self.path))
            elif self.path.startswith("/api/job"):
                _serve_job(self)
            elif self.path.startswith("/api/workspace"):
                _serve_workspace(self)
            elif self.path.startswith("/api/apps/config"):
                _serve_apps_config(self)
            elif self.path.startswith("/api/git/user"):
                _write_json(self, router.serve_git_user(self.path))
            elif self.path.startswith("/api/git/branches"):
                _write_json(self, router.serve_git_branches(self.path))
            elif self.path.startswith("/api/git/status"):
                _write_json(self, router.serve_git_status(self.path))
            elif self.path.startswith("/api/git/changes"):
                _write_json(self, router.serve_git_changes(self.path))
            elif self.path.startswith("/api/git/branch/ci-status"):
                _write_json(self, router.serve_git_branch_ci_status(self.path))
            elif self.path.startswith("/api/git/conflicts"):
                _write_json(self, router.serve_git_conflicts(self.path))
            elif self.path.startswith("/api/git/stashes"):
                _write_json(self, router.serve_git_stashes(self.path))
            elif self.path.startswith("/api/git/diff"):
                _write_json(self, router.serve_git_diff(self.path))
            elif self.path.startswith("/api/git/commits"):
                _write_json(self, router.serve_git_commits(self.path))
            elif self.path.startswith("/api/git/worktrees"):
                _write_json(self, router.serve_git_worktrees(self.path))
            else:
                _serve_api_not_found(self)
        else:
            _serve_static(self)

    def do_POST(self):
        if not _check_host_and_origin(self):
            return

        if self.path.startswith("/api/"):
            if not _check_api_auth(self):
                return
            
            payload = _safe_read_json(self)
            if payload is None:
                return

            if self.path.startswith("/api/git/fetch"):
                _write_json(self, router.handle_git_fetch(payload))
            elif self.path.startswith("/api/job/stop"):
                _handle_job_stop(self, payload)
            elif self.path.startswith("/api/workspace/switch"):
                _handle_workspace_switch(self, payload)
            elif self.path.startswith("/api/git/sync-all-branches"):
                _write_json(self, router.handle_git_sync_all_branches(payload))
            elif self.path.startswith("/api/git/branch/action"):
                _write_json(self, router.handle_git_branch_action(payload))
            elif self.path.startswith("/api/git/pull"):
                _write_json(self, router.handle_git_pull(payload))
            elif self.path.startswith("/api/git/push"):
                _write_json(self, router.handle_git_push(payload))
            elif self.path.startswith("/api/git/ai/commit-message"):
                _write_json(self, router.handle_git_ai_commit_message_async(payload))
            elif self.path.startswith("/api/git/commit"):
                _write_json(self, router.handle_git_commit_async(payload))
            elif self.path.startswith("/api/git/terminal/run"):
                _write_json(self, router.handle_git_terminal_run(payload))
            elif self.path.startswith("/api/git/stash-pull-pop"):
                _write_json(self, router.handle_git_stash_pull_pop(payload))
            elif self.path.startswith("/api/git/stash/create"):
                _write_json(self, router.handle_git_stash_create(payload))
            elif self.path.startswith("/api/git/stash/apply"):
                _write_json(self, router.handle_git_stash_apply(payload))
            elif self.path.startswith("/api/git/stash/drop"):
                _write_json(self, router.handle_git_stash_drop(payload))
            elif self.path.startswith("/api/git/stash/pop"):
                _write_json(self, router.handle_git_stash_pop(payload))
            elif self.path.startswith("/api/git/conflict/resolve"):
                _write_json(self, router.handle_git_conflict_resolve(payload))
            elif self.path.startswith("/api/git/tag/create"):
                _write_json(self, router.handle_git_tag_create(payload))
            elif self.path.startswith("/api/git/tags/compare"):
                _write_json(self, router.handle_git_tags_compare(payload))
            elif self.path.startswith("/api/git/tags/recommend-bump"):
                _write_json(self, router.handle_git_recommend_bump(payload))
            elif self.path.startswith("/api/git/tags"):
                _write_json(self, router.handle_git_tags_list(payload))
            elif self.path.startswith("/api/git/tag/edit"):
                _write_json(self, router.handle_git_tag_edit(payload))
            elif self.path.startswith("/api/git/tag/delete"):
                _write_json(self, router.handle_git_tag_delete(payload))
            elif self.path.startswith("/api/git/tag/push"):
                _write_json(self, router.handle_git_tag_push(payload))
            elif self.path.startswith("/api/git/branch/create"):
                _write_json(self, router.handle_git_branch_create(payload))
            elif self.path.startswith("/api/git/branch/delete"):
                _write_json(self, router.handle_git_branch_delete(payload))
            elif self.path.startswith("/api/git/release/create"):
                _write_json(self, router.handle_git_release_create(payload))
            elif self.path.startswith("/api/git/contributors"):
                _write_json(self, router.handle_git_contributors(payload))
            elif self.path.startswith("/api/git/worktree/add"):
                _write_json(self, router.handle_git_worktree_add(payload))
            elif self.path.startswith("/api/git/worktree/remove"):
                _write_json(self, router.handle_git_worktree_remove(payload))
            elif self.path.startswith("/api/git/worktree/prune"):
                _write_json(self, router.handle_git_worktree_prune(payload))
            else:
                _serve_api_not_found(self)
        else:
            self.send_error(404, "Not Found")


def main():
    global PORT, HOST
    import argparse
    import threading
    import webbrowser

    parser = argparse.ArgumentParser(description="DevGit - Standalone Multi-Repo Git Dashboard")
    parser.add_argument("--workspace", "-w", default=os.environ.get("WORKSPACE_ROOT", os.getcwd()), help="Path to workspace root")
    parser.add_argument("--port", "-p", type=int, default=PORT, help=f"Server port (default: {PORT})")
    parser.add_argument("--host", default=HOST, help=f"Server host (default: {HOST})")
    parser.add_argument("--open", "-o", action="store_true", help="Automatically open DevGit in browser")
    args = parser.parse_args()

    target_workspace = Path(args.workspace).expanduser().resolve()
    router.set_workspace_root(target_workspace)
    PORT = args.port
    HOST = args.host
    session_token = router.get_session_token()

    dashboard_url = f"http://{HOST}:{PORT}/?token={session_token}"

    print(f"==================================================")
    print(f" 🔄 DevGit - Standalone Multi-Repo Git Dashboard")
    print(f"==================================================")
    print(f"Target Workspace: {target_workspace}")
    print(f"Listening on:     http://{HOST}:{PORT}")
    print(f"Session Token:    {session_token}")
    print(f"Dashboard URL:    {dashboard_url}")
    print(f"==================================================")

    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(dashboard_url)).start()

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), GitHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down DevGit server.")


if __name__ == "__main__":
    main()
