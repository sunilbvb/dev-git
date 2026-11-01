import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules import branches, scoped_branch
from tests.test_scoped_branch import make_repo


def merged(p):
    """True when origin/main contains develop."""
    return subprocess.run(["git", "-C", str(p), "merge-base", "--is-ancestor", "develop", "origin/main"]).returncode == 0


class TestScopedMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        (root / "origins").mkdir()
        self.app = root / "apps" / "app1"
        self.pkg = root / "packages" / "pkg1"
        for p in (self.app, self.pkg):
            make_repo(p, root / "origins")
            subprocess.run(["git", "-C", str(p), "push", "-u", "origin", "develop"], check=True, capture_output=True)
        self.addCleanup(set_workspace_root, get_workspace_root())
        set_workspace_root(root)
        patcher = mock.patch.object(
            scoped_branch, "resolve_scope_repos",
            return_value=(True, {"package": "app1", "repos": [self.app, self.pkg]}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_it(self, **kw):
        data = {"repoPath": str(self.app), "branch": "develop", "action": "merge", "targetBranch": "main",
                "useMelos": True}
        data.update(kw)
        return branches.handle_git_branch_action(data)

    def test_merges_and_pushes_every_repo_then_noop(self):
        res = self.run_it()
        self.assertTrue(res["success"], res)
        self.assertEqual(sorted(res["mergedRepos"]), ["app1", "pkg1"])
        for p in (self.app, self.pkg):
            self.assertTrue(merged(p))
        again = self.run_it()
        self.assertTrue(again["success"], again)
        self.assertEqual((again["mergedRepos"], sorted(again["noOpRepos"])), ([], ["app1", "pkg1"]))
        self.assertEqual(len(again["noOpWarnings"]), 2)

    def test_dirty_package_blocks_everything(self):
        (self.pkg / "dirty.txt").write_text("x")
        res = self.run_it()
        self.assertFalse(res["success"])
        self.assertIn("pkg1", res["error"])
        self.assertFalse(merged(self.app))

    def test_melos_off_merges_only_app(self):
        res = self.run_it(useMelos=False)
        self.assertTrue(res["success"], res)
        self.assertTrue(merged(self.app))
        self.assertFalse(merged(self.pkg))


if __name__ == "__main__":
    unittest.main()
