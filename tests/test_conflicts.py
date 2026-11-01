import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules.conflicts import (
    serve_git_conflicts_list,
    serve_git_conflict_file,
    handle_git_conflict_resolve,
    handle_git_conflict_abort
)


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)


class TestGitConflicts(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_workspace_root, get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = root / "conflict_repo"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Tester")

        # Base commit
        (self.repo / "file.txt").write_text("base line\n")
        git(self.repo, "add", "file.txt")
        git(self.repo, "commit", "-m", "base")

        # Feature branch with change
        git(self.repo, "checkout", "-b", "feature")
        (self.repo / "file.txt").write_text("feature line\n")
        git(self.repo, "commit", "-am", "feature change")

        # Main branch with conflicting change
        git(self.repo, "checkout", "main")
        (self.repo / "file.txt").write_text("main conflicting line\n")
        git(self.repo, "commit", "-am", "main change")

        set_workspace_root(root)

    def _trigger_conflict(self):
        git(self.repo, "merge", "feature")

    def test_detect_conflict_and_file_details(self):
        self._trigger_conflict()

        # Check list conflicts
        res = serve_git_conflicts_list(f"/api/git/conflicts?repoPath={self.repo}")
        self.assertTrue(res["success"], res)
        self.assertEqual(res["operation"], "merge")
        self.assertIn("file.txt", res["conflicts"])

        # Check conflict file detail
        detail = serve_git_conflict_file(f"/api/git/conflicts/file?repoPath={self.repo}&file=file.txt")
        self.assertTrue(detail["success"], detail)
        self.assertTrue(detail["hasConflictMarkers"])
        self.assertEqual(detail["conflictCount"], 1)
        self.assertIn("main conflicting line", detail["conflictBlocks"][0]["ours"])
        self.assertIn("feature line", detail["conflictBlocks"][0]["theirs"])

    def test_resolve_conflict_ours_and_theirs(self):
        self._trigger_conflict()

        # Resolve using ours
        res = handle_git_conflict_resolve({
            "repoPath": str(self.repo),
            "file": "file.txt",
            "strategy": "ours"
        })
        self.assertTrue(res["success"], res)
        self.assertTrue(res["allResolved"])
        content = (self.repo / "file.txt").read_text()
        self.assertEqual(content, "main conflicting line\n")

    def test_resolve_conflict_custom(self):
        self._trigger_conflict()

        # Resolve using custom content
        res = handle_git_conflict_resolve({
            "repoPath": str(self.repo),
            "file": "file.txt",
            "strategy": "custom",
            "content": "custom merged line\n"
        })
        self.assertTrue(res["success"], res)
        self.assertTrue(res["allResolved"])
        content = (self.repo / "file.txt").read_text()
        self.assertEqual(content, "custom merged line\n")

    def test_abort_conflict(self):
        self._trigger_conflict()
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())

        res = handle_git_conflict_abort({"repoPath": str(self.repo)})
        self.assertTrue(res["success"], res)
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())


if __name__ == "__main__":
    unittest.main()
