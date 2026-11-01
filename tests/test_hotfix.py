import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules.branches import handle_git_hotfix_create, handle_git_hotfix_finish


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


class TestGitHotfix(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_workspace_root, get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = root / "hotfix_repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")

        (self.repo / "app.txt").write_text("v1.0.0")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "initial release")

        # Create develop branch
        git(self.repo, "checkout", "-b", "develop")
        (self.repo / "dev.txt").write_text("dev work")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "develop commit")

        git(self.repo, "checkout", "main")
        set_workspace_root(root)

    def test_hotfix_lifecycle(self):
        # 1. Create hotfix
        res = handle_git_hotfix_create({
            "repoPath": str(self.repo),
            "name": "v1.0.1",
            "baseBranch": "main"
        })
        self.assertTrue(res["success"], res)
        curr = subprocess.run(["git", "-C", str(self.repo), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(curr, "hotfix/v1.0.1")

        # Apply fix
        (self.repo / "app.txt").write_text("v1.0.1 patched")
        git(self.repo, "commit", "-am", "fix security bug")

        # 2. Finish hotfix
        fin = handle_git_hotfix_finish({
            "repoPath": str(self.repo),
            "branchName": "hotfix/v1.0.1",
            "tagVersion": "v1.0.1",
            "push": False
        })
        self.assertTrue(fin["success"], fin)

        # Check tag exists
        tags = subprocess.run(["git", "-C", str(self.repo), "tag"], capture_output=True, text=True).stdout
        self.assertIn("v1.0.1", tags)

        # Check main has fix
        git(self.repo, "checkout", "main")
        self.assertEqual((self.repo / "app.txt").read_text(), "v1.0.1 patched")

        # Check develop also received the fix
        git(self.repo, "checkout", "develop")
        self.assertEqual((self.repo / "app.txt").read_text(), "v1.0.1 patched")

        # Check hotfix branch was deleted
        branches = subprocess.run(["git", "-C", str(self.repo), "branch"], capture_output=True, text=True).stdout
        self.assertNotIn("hotfix/v1.0.1", branches)


if __name__ == "__main__":
    unittest.main()
