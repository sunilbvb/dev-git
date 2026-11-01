import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules.graph import serve_git_graph


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


class TestGitGraph(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_workspace_root, get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = root / "graph_repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")

        (self.repo / "init.txt").write_text("1")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "first commit")

        git(self.repo, "tag", "-a", "v1.0.0", "-m", "v1.0.0")

        (self.repo / "init.txt").write_text("2")
        git(self.repo, "commit", "-am", "second commit")

        set_workspace_root(root)

    def test_serve_git_graph(self):
        res = serve_git_graph(f"/api/git/graph?repoPath={self.repo}&limit=10")
        self.assertTrue(res["success"], res)
        self.assertEqual(res["count"], 2)
        commits = res["commits"]

        self.assertEqual(commits[0]["subject"], "second commit")
        self.assertTrue(commits[0]["isHead"])
        self.assertEqual(commits[1]["subject"], "first commit")

        # Verify tag ref detection
        tag_refs = [r for r in commits[1]["refs"] if r["type"] == "tag"]
        self.assertEqual(len(tag_refs), 1)
        self.assertEqual(tag_refs[0]["name"], "v1.0.0")


if __name__ == "__main__":
    unittest.main()
