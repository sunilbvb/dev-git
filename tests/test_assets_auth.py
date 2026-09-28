import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from devgit.core import auth, jobs
from devgit import server


class TestAssetsAuthAndPayload(unittest.TestCase):
    def setUp(self):
        auth.set_session_token("secret-token-abc")

    def test_job_pruning(self):
        # Create 115 jobs
        for i in range(115):
            j_id = jobs.create_job("test", f"cmd_{i}")
            jobs.complete_job(j_id, "success")
        
        # Verify job list does not exceed 100
        with jobs._JOBS_LOCK:
            jobs._prune_jobs_locked()
            self.assertLessEqual(len(jobs._JOBS), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
