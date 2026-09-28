import threading
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("devgit.jobs")

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_NEXT_JOB_ID = 1
_MAX_LOG_CHARS = 40000
_JOB_RETENTION_SECONDS = 600  # 10 minutes
_MAX_JOBS_COUNT = 100


def _prune_jobs_locked() -> None:
    now = time.time()
    to_delete = []
    
    # 1. Prune finished jobs older than _JOB_RETENTION_SECONDS
    for j_id, job in _JOBS.items():
        if job.get("status") in {"success", "error"}:
            ended_at = job.get("endedAt") or job.get("startedAt") or 0
            if now - ended_at > _JOB_RETENTION_SECONDS:
                to_delete.append(j_id)
                
    for j_id in to_delete:
        _JOBS.pop(j_id, None)

    # 2. Cap max finished jobs count if total > _MAX_JOBS_COUNT
    if len(_JOBS) > _MAX_JOBS_COUNT:
        finished_jobs = sorted(
            [j for j in _JOBS.values() if j.get("status") in {"success", "error"}],
            key=lambda x: x.get("endedAt") or 0
        )
        excess = len(_JOBS) - _MAX_JOBS_COUNT
        for fj in finished_jobs[:excess]:
            _JOBS.pop(fj.get("id"), None)


def new_job_id() -> str:
    global _NEXT_JOB_ID
    with _JOBS_LOCK:
        _prune_jobs_locked()
        job_id = str(_NEXT_JOB_ID)
        _NEXT_JOB_ID += 1
        return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        _prune_jobs_locked()
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
        _prune_jobs_locked()
