#!/usr/bin/env python3
import http.server
import json
import os
import socketserver
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import router

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
WORKSPACE_ASSETS_DIR = ROOT_DIR / "workspace_assets"

PORT = 8086
HOST = "127.0.0.1"


def _serve_static(handler):
    parsed = urllib.parse.urlparse(handler.path)
    relative = parsed.path.lstrip("/") or "index.html"
    if relative.startswith("workspace_assets/"):
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
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _write_json(handler, data: dict, status: int = 200):
    payload = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _safe_read_json(handler):
    content_length = int(handler.headers.get("Content-Length", 0))
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
        "workspace": str(router._WORKSPACE_ROOT),
        "name": router._WORKSPACE_ROOT.name
    })


def _handle_workspace_switch(handler, data: dict):
    new_path_str = (data.get("workspace") or data.get("path") or "").strip()
    if not new_path_str:
        _write_json(handler, {"success": False, "error": "Missing workspace path"}, status=400)
        return

    new_path = Path(new_path_str).expanduser().resolve()
    if not new_path.exists() or not new_path.is_dir():
        _write_json(handler, {"success": False, "error": f"Directory not found: {new_path}"}, status=404)
        return

    router._WORKSPACE_ROOT = new_path
    if router._CACHE_FILE.exists():
        try:
            router._CACHE_FILE.unlink()
        except Exception:
            pass

    print(f"[DevGit] Workspace switched to: {new_path}")
    _write_json(handler, {
        "success": True,
        "workspace": str(new_path),
        "name": new_path.name
    })


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
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
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
        elif self.path.startswith("/api/"):
            _serve_api_not_found(self)
        else:
            _serve_static(self)

    def do_POST(self):
        if self.path.startswith("/api/git/fetch"):
            _write_json(self, router.handle_git_fetch(_safe_read_json(self)))
        elif self.path.startswith("/api/job/stop"):
            _handle_job_stop(self, _safe_read_json(self))
        elif self.path.startswith("/api/workspace/switch"):
            _handle_workspace_switch(self, _safe_read_json(self))
        elif self.path.startswith("/api/git/sync-all-branches"):
            _write_json(self, router.handle_git_sync_all_branches(_safe_read_json(self)))
        elif self.path.startswith("/api/git/branch/action"):
            _write_json(self, router.handle_git_branch_action(_safe_read_json(self)))
        elif self.path.startswith("/api/git/pull"):
            _write_json(self, router.handle_git_pull(_safe_read_json(self)))
        elif self.path.startswith("/api/git/push"):
            _write_json(self, router.handle_git_push(_safe_read_json(self)))
        elif self.path.startswith("/api/git/ai/commit-message"):
            _write_json(self, router.handle_git_ai_commit_message_async(_safe_read_json(self)))
        elif self.path.startswith("/api/git/commit"):
            _write_json(self, router.handle_git_commit_async(_safe_read_json(self)))
        elif self.path.startswith("/api/git/terminal/run"):
            _write_json(self, router.handle_git_terminal_run(_safe_read_json(self)))
        elif self.path.startswith("/api/git/stash-pull-pop"):
            _write_json(self, router.handle_git_stash_pull_pop(_safe_read_json(self)))
        elif self.path.startswith("/api/git/stash/create"):
            _write_json(self, router.handle_git_stash_create(_safe_read_json(self)))
        elif self.path.startswith("/api/git/stash/apply"):
            _write_json(self, router.handle_git_stash_apply(_safe_read_json(self)))
        elif self.path.startswith("/api/git/stash/drop"):
            _write_json(self, router.handle_git_stash_drop(_safe_read_json(self)))
        elif self.path.startswith("/api/git/stash/pop"):
            _write_json(self, router.handle_git_stash_pop(_safe_read_json(self)))
        elif self.path.startswith("/api/git/conflict/resolve"):
            _write_json(self, router.handle_git_conflict_resolve(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tag/create"):
            _write_json(self, router.handle_git_tag_create(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tags/compare"):
            _write_json(self, router.handle_git_tags_compare(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tags/recommend-bump"):
            _write_json(self, router.handle_git_recommend_bump(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tags"):
            _write_json(self, router.handle_git_tags_list(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tag/edit"):
            _write_json(self, router.handle_git_tag_edit(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tag/delete"):
            _write_json(self, router.handle_git_tag_delete(_safe_read_json(self)))
        elif self.path.startswith("/api/git/tag/push"):
            _write_json(self, router.handle_git_tag_push(_safe_read_json(self)))
        elif self.path.startswith("/api/git/branch/create"):
            _write_json(self, router.handle_git_branch_create(_safe_read_json(self)))
        elif self.path.startswith("/api/git/branch/finish"):
            _write_json(self, router.handle_git_branch_finish(_safe_read_json(self)))
        elif self.path.startswith("/api/git/branch/delete"):
            _write_json(self, router.handle_git_branch_delete(_safe_read_json(self)))
        elif self.path.startswith("/api/git/release/create"):
            _write_json(self, router.handle_git_release_create(_safe_read_json(self)))
        elif self.path.startswith("/api/git/contributors"):
            _write_json(self, router.handle_git_contributors(_safe_read_json(self)))
        elif self.path.startswith("/api/"):
            _serve_api_not_found(self)
        else:
            self.send_error(404, "Not Found")


def main():
    global PORT, HOST
    import argparse
    import threading
    import webbrowser

    parser = argparse.ArgumentParser(description="DevGit - Standalone Multi-Repo Git Dashboard")
    parser.add_argument("--workspace", "-w", default=os.environ.get("WORKSPACE_ROOT", os.getcwd()), help="Path to workspace root (default: current directory)")
    parser.add_argument("--port", "-p", type=int, default=PORT, help=f"Server port (default: {PORT})")
    parser.add_argument("--host", default=HOST, help=f"Server host (default: {HOST})")
    parser.add_argument("--open", "-o", action="store_true", help="Automatically open DevGit in browser")
    args = parser.parse_args()

    target_workspace = Path(args.workspace).expanduser().resolve()
    router._WORKSPACE_ROOT = target_workspace
    PORT = args.port
    HOST = args.host

    print(f"==================================================")
    print(f" 🔄 DevGit - Standalone Multi-Repo Git Dashboard")
    print(f"==================================================")
    print(f"Target Workspace: {target_workspace}")
    print(f"Listening on:     http://{HOST}:{PORT}")
    print(f"==================================================")

    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), GitHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down DevGit server.")


if __name__ == "__main__":
    main()
