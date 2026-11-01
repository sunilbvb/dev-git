import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules import release, scoped_branch
from tests.test_scoped_branch import make_repo


def tags(p):
    out = subprocess.run(["git", "-C", str(p), "tag", "-l"], capture_output=True, text=True).stdout
    return out.split()


def remote_tags(p):
    out = subprocess.run(["git", "-C", str(p), "ls-remote", "--tags", "origin"], capture_output=True, text=True).stdout
    return [line.split("refs/tags/")[1] for line in out.splitlines() if not line.endswith("^{}")]


class TestScopedTag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        (root / "origins").mkdir()
        self.app = root / "apps" / "gyo_business"
        self.pkg = root / "packages" / "pkg1"
        for p in (self.app, self.pkg):
            make_repo(p, root / "origins")
        self.addCleanup(set_workspace_root, get_workspace_root())
        set_workspace_root(root)
        patcher = mock.patch.object(
            scoped_branch, "resolve_scope_repos",
            return_value=(True, {"package": "gyo_business", "repos": [self.app, self.pkg]}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_it(self, **kw):
        data = {"repoPath": str(self.app), "tagName": "1.0.8+185", "message": "rel", "useMelos": True}
        data.update(kw)
        return release.handle_git_tag_create(data)

    def test_dry_run_changes_nothing(self):
        res = self.run_it(dryRun=True)
        self.assertTrue(res["success"])
        self.assertEqual(tags(self.app) + tags(self.pkg), [])

    def test_app_plain_packages_prefixed(self):
        res = self.run_it()
        self.assertTrue(res["success"], res)
        self.assertEqual(tags(self.app), ["v1.0.8+185"])
        self.assertEqual(tags(self.pkg), ["gyo-business-v1.0.8+185"])
        self.assertEqual((res["appTagName"], res["pkgTagPrefix"], res["createdCount"]),
                         ("v1.0.8+185", "gyo-business-", 2))
        self.assertFalse(res["pushed"])

    def test_existing_skipped_and_push(self):
        subprocess.run(["git", "-C", str(self.app), "tag", "-a", "v1.0.8+185", "-m", "x"], check=True)
        res = self.run_it(pushToRemote=True)
        self.assertTrue(res["success"], res)
        self.assertEqual((res["createdCount"], res["skippedCount"]), (1, 1))
        self.assertEqual(remote_tags(self.pkg), ["gyo-business-v1.0.8+185"])
        self.assertEqual(remote_tags(self.app), [])

    def test_melos_off_tags_only_app(self):
        res = self.run_it(useMelos=False)
        self.assertTrue(res["success"], res)
        self.assertEqual(tags(self.app), ["v1.0.8+185"])
        self.assertEqual(tags(self.pkg), [])


if __name__ == "__main__":
    unittest.main()


class TestPubspecVersionInBranches(unittest.TestCase):
    def test_branches_response_exposes_pubspec_version(self):
        from devgit.modules import branches
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "origins").mkdir()
            repo = root / "apps" / "app1"
            make_repo(repo, root / "origins")
            self.addCleanup(set_workspace_root, get_workspace_root())
            set_workspace_root(root)
            self.assertEqual(branches.serve_git_branches(f"/api/git/branches?quick=true&repoPath={repo}")["pubspecVersion"], "")
            (repo / "pubspec.yaml").write_text("name: x\nversion: 1.0.9+186  # note\n")
            self.assertEqual(branches.serve_git_branches(f"/api/git/branches?quick=true&repoPath={repo}")["pubspecVersion"], "1.0.9+186")
