import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any

from devgit.core.git import get_workspace_root, discover_git_repos, run_git
from devgit.core.jobs import create_job, append_job_log, complete_job

logger = logging.getLogger("devgit.ai")

OLLAMA_BASE_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434').rstrip('/')
AI_MAX_DIFF_CHARS = int(os.environ.get('AI_MAX_DIFF_CHARS', '120000'))


def resolve_ollama_model() -> str:
    env_model = os.environ.get("OLLAMA_MODEL")
    if env_model:
        return env_model
    try:
        url = f"{OLLAMA_BASE_URL}/api/tags"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            if "deepseek-r1:latest" in models:
                return "deepseek-r1:latest"
            for m in models:
                if "deepseek-r1" in m:
                    return m
            if models:
                return models[0]
    except Exception as e:
        logger.debug(f"Failed to query Ollama tags: {e}")
    return "deepseek-r1:latest"


def ollama_generate(system: str, prompt: str) -> str:
    model = resolve_ollama_model()
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 160,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(body or "{}")
            return str(obj.get("response") or "").strip()
    except Exception as e:
        raise RuntimeError(f"Ollama generation error: {e}") from e


def handle_git_ai_commit_message_async(data: dict) -> Dict[str, Any]:
    repo_path = str(data.get("repoPath") or "").strip()
    if not repo_path:
        return {"success": False, "error": "Missing repoPath"}

    workspace_root = get_workspace_root()
    repos = discover_git_repos(workspace_root)
    target = Path(repo_path).resolve()
    if target not in repos:
        return {"success": False, "error": "Unknown repoPath"}

    code, diff_staged, _ = run_git(target, ["diff", "--staged"])
    code_u, diff_unstaged, _ = run_git(target, ["diff"])
    diff = diff_staged if diff_staged else diff_unstaged

    if not diff:
        return {"success": False, "error": "No staged or unstaged changes found"}

    custom_prompt = str(data.get("customPrompt") or data.get("systemPrompt") or "").strip()
    system_prompt = custom_prompt if custom_prompt else "You are a professional software engineer. Write a concise, clear conventional commit message for the given diff."

    job_id = create_job("ai_commit_msg", f"Generate AI commit message for {target.name}")

    def _generate():
        try:
            msg = ollama_generate(system_prompt, f"Git diff:\n{diff[:AI_MAX_DIFF_CHARS]}")
            append_job_log(job_id, "output", msg)
            complete_job(job_id, status="success")
        except Exception as e:
            logger.exception("AI commit message generation failed")
            complete_job(job_id, status="error", error_msg=str(e))

    import threading
    threading.Thread(target=_generate, daemon=True).start()
    return {"success": True, "jobId": job_id}
