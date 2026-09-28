import threading
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("devgit.jobs")

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_NEXT_JOB_ID = 1
_MAX_LOG_CHARS = 40000


def new_job_id() -> str:
    global _NEXT_JOB_ID
    with _JOBS_LOCK:
        job_id = str(_NEXT_JOB_ID)
        _NEXT_JOB_ID += 1
        return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if k not in {"process", "pgid"}}


def create_job(job_type: str, command: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    job_id = new_job_id()
    job_data: Dict[str, Any] = {
        "id": job_id,
        "type": job_type,
        "status": "running",
        "startedAt": time.time(),
        "command": command,
        "output": "",
        "error": "",
    }
    if metadata:
        job_data.update(metadata)
    with _JOBS_LOCK:
        _JOBS[job_id] = job_data
    return job_id


def append_job_log(job_id: str, field: str, text: str) -> None:
    if not text:
        return
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        curr = job.get(field, "")
        combined = curr + text
        if len(combined) > _MAX_LOG_CHARS:
            combined = combined[-_MAX_LOG_CHARS:]
        job[field] = combined


def complete_job(job_id: str, status: str = "success", error_msg: Optional[str] = None) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job["status"] = status
            job["endedAt"] = time.time()
            if error_msg:
                job["error"] = ((job.get("error") or "") + f"\n{error_msg}").strip()
