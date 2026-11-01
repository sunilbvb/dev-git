import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules.staging import serve_git_status_files, handle_git_stage


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


class TestGitStaging(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_workspace_root, get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = root / "test_repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")

        # Initial commit
        (self.repo / "tracked.txt").write_text("initial")
        git(self.repo, "add", "tracked.txt")
        git(self.repo, "commit", "-m", "init")

        set_workspace_root(root)

    def test_status_files_categorization(self):
        # Modify tracked file (unstaged)
        (self.repo / "tracked.txt").write_text("modified")
        # New untracked file
        (self.repo / "untracked.txt").write_text("new")

        res = serve_git_status_files(f"/api/git/files?repoPath={self.repo}")
        self.assertTrue(res["success"], res)
        self.assertEqual(len(res["staged"]), 0)
        self.assertEqual(len(res["unstaged"]), 1)
        self.assertEqual(res["unstaged"][0]["path"], "tracked.txt")
        self.assertEqual(len(res["untracked"]), 1)
        self.assertEqual(res["untracked"][0]["path"], "untracked.txt")

    def test_stage_and_unstage_files(self):
        (self.repo / "file1.txt").write_text("1")
        (self.repo / "file2.txt").write_text("2")

        # Stage file1
        res = handle_git_stage({
            "repoPath": str(self.repo),
            "files": ["file1.txt"],
            "action": "stage"
        })
        self.assertTrue(res["success"], res)

        status = serve_git_status_files(f"/api/git/files?repoPath={self.repo}")
        self.assertEqual(len(status["staged"]), 1)
        self.assertEqual(status["staged"][0]["path"], "file1.txt")
        self.assertEqual(len(status["untracked"]), 1)

        # Unstage file1
        res_un = handle_git_stage({
            "repoPath": str(self.repo),
            "files": ["file1.txt"],
            "action": "unstage"
        })
        self.assertTrue(res_un["success"], res_un)
        status2 = serve_git_status_files(f"/api/git/files?repoPath={self.repo}")
        self.assertEqual(len(status2["staged"]), 0)

    def test_stage_all_and_unstage_all(self):
        (self.repo / "a.txt").write_text("a")
        (self.repo / "b.txt").write_text("b")

        res = handle_git_stage({
            "repoPath": str(self.repo),
            "action": "stage_all"
        })
        self.assertTrue(res["success"], res)
        status = serve_git_status_files(f"/api/git/files?repoPath={self.repo}")
        self.assertGreaterEqual(len(status["staged"]), 2)

        res_un = handle_git_stage({
            "repoPath": str(self.repo),
            "action": "unstage_all"
        })
        self.assertTrue(res_un["success"], res_un)
        status2 = serve_git_status_files(f"/api/git/files?repoPath={self.repo}")
        self.assertEqual(len(status2["staged"]), 0)


if __name__ == "__main__":
    unittest.main()
