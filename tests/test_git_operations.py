import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

import router


class TestGitOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = ROOT_DIR
        router.set_workspace_root(cls.workspace)

    def test_git_tags_list(self):
        res = router.handle_git_tags_list({"repoPath": str(self.workspace)})
        self.assertTrue(res.get("success"))
        self.assertIn("tags", res)
        self.assertIsInstance(res["tags"], list)

    def test_recommend_bump(self):
        res = router.handle_git_recommend_bump({"repoPath": str(self.workspace)})
        self.assertTrue(res.get("success"))
        self.assertIn("recommendations", res)
        rec = res["recommendations"]
        self.assertIn("patch", rec)
        self.assertIn("minor", rec)
        self.assertIn("major", rec)

    def test_serve_git_commits(self):
        res = router.serve_git_commits(f"/api/git/commits?repoPath={self.workspace}&limit=5")
        self.assertTrue(res.get("success"))
        self.assertIn("commits", res)
        self.assertIsInstance(res["commits"], list)
        if res["commits"]:
            commit = res["commits"][0]
            self.assertIn("hash", commit)
            self.assertIn("author", commit)
            self.assertIn("subject", commit)

    def test_contributors(self):
        res = router.handle_git_contributors({"repoPath": str(self.workspace)})
        self.assertTrue(res.get("success"))
        self.assertIn("contributors", res)
        self.assertIsInstance(res["contributors"], list)

    def test_tags_compare(self):
        res = router.handle_git_tags_compare({
            "repoPath": str(self.workspace),
            "fromTag": "HEAD~1",
            "toTag": "HEAD"
        })
        self.assertTrue(res.get("success"))
        self.assertIn("commits", res)
        self.assertEqual(res.get("count"), 1)
        self.assertEqual(len(res.get("commits", [])), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
