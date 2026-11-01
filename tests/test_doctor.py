import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules.doctor import serve_git_doctor, handle_git_doctor_fix


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


class TestGitDoctor(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_workspace_root, get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = root / "doctor_repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")

        (self.repo / "main.txt").write_text("main")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "init")

        set_workspace_root(root)

    def test_clean_health_check(self):
        res = serve_git_doctor(f"/api/git/doctor?repoPath={self.repo}")
        self.assertTrue(res["success"], res)
        self.assertEqual(res["health"], "healthy")
        self.assertEqual(res["errorCount"], 0)

    def test_merged_branch_detected_and_fixed(self):
        # Create and merge a branch
        git(self.repo, "checkout", "-b", "feature/merged-task")
        (self.repo / "feat.txt").write_text("feat")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "feat commit")

        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "feature/merged-task")

        # Doctor should detect merged branch
        res = serve_git_doctor(f"/api/git/doctor?repoPath={self.repo}")
        self.assertTrue(res["success"], res)
        branch_check = next((c for c in res["checks"] if c["id"] == "merged_branches"), None)
        self.assertIsNotNone(branch_check)
        self.assertEqual(branch_check["type"], "warning")
        self.assertIn("feature/merged-task", branch_check["details"])

        # Fix: delete merged branch
        fix_res = handle_git_doctor_fix({
            "repoPath": str(self.repo),
            "action": "delete_branch",
            "item": "feature/merged-task"
        })
        self.assertTrue(fix_res["success"], fix_res)

        # Check it is gone
        branches = subprocess.run(["git", "-C", str(self.repo), "branch"], capture_output=True, text=True).stdout
        self.assertNotIn("feature/merged-task", branches)


if __name__ == "__main__":
    unittest.main()
