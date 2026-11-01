import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import set_workspace_root, get_workspace_root
from devgit.modules import scoped_branch


def git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def make_repo(path: Path, origin_root: Path):
    path.mkdir(parents=True)
    bare = origin_root / f"{path.name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("1")
    git(path, "add", ".")
    git(path, "commit", "-m", "init")
    git(path, "remote", "add", "origin", str(bare))
    git(path, "push", "-u", "origin", "main")
    git(path, "checkout", "-b", "develop")
    (path / "dev.txt").write_text("dev only")
    git(path, "add", ".")
    git(path, "commit", "-m", "dev work")


class TestScopedBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.root = root
        (root / "origins").mkdir()
        self.app = root / "apps" / "app1"
        self.pkg = root / "packages" / "pkg1"
        for p in (self.app, self.pkg):
            make_repo(p, root / "origins")
        self.addCleanup(set_workspace_root, get_workspace_root())
        set_workspace_root(root)
        patcher = mock.patch.object(
            scoped_branch, "resolve_scope_repos",
            return_value=(True, {"package": "app1", "repos": [self.app, self.pkg]}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_it(self, **kw):
        data = {"repoPath": str(self.app), "branchName": "hotfix/v1.0.8/x", "baseBranch": "main"}
        data.update(kw)
        return scoped_branch.handle_git_branch_create_scoped(data)

    def head(self, p):
        return subprocess.run(["git", "-C", str(p), "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True).stdout.strip()

    def test_dry_run_changes_nothing(self):
        res = self.run_it(dryRun=True)
        self.assertTrue(res["success"])
        self.assertFalse(res["changed"])
        self.assertEqual(self.head(self.app), "develop")

    def test_app_plain_name_packages_nested(self):
        res = self.run_it()
        self.assertTrue(res["success"], res)
        self.assertEqual(self.head(self.app), "hotfix/v1.0.8/x")
        self.assertEqual(self.head(self.pkg), "hotfix/app1/v1.0.8/x")
        for p in (self.app, self.pkg):
            self.assertFalse((p / "dev.txt").exists())

    def test_use_melos_via_create_handler(self):
        from devgit.modules.branches import handle_git_branch_create
        res = handle_git_branch_create({"repoPath": str(self.app), "branchName": "features/v1.0.8/y",
                                        "baseBranch": "main", "useMelos": True})
        self.assertTrue(res["success"], res)
        self.assertEqual(self.head(self.pkg), "features/app1/v1.0.8/y")

    def test_package_name_rule(self):
        f = scoped_branch.package_branch_name
        self.assertEqual(f("hotfix/v1.0.8/x", Path("/w/apps/gyo_business")), "hotfix/gyo-business/v1.0.8/x")
        self.assertEqual(f("hotfix/gyo-business/v1.0.8/x", Path("/w/apps/gyo_business")),
                         "hotfix/gyo-business/v1.0.8/x")

    def test_non_standard_base_nested_for_packages(self):
        git(self.app, "branch", "hotfix/v1.0.8/h", "main")
        git(self.pkg, "branch", "hotfix/app1/v1.0.8/h", "main")
        res = self.run_it(branchName="bugfix/v1.1.3/z", baseBranch="hotfix/v1.0.8/h")
        self.assertTrue(res["success"], res)
        self.assertEqual(self.head(self.app), "bugfix/v1.1.3/z")
        self.assertEqual(self.head(self.pkg), "bugfix/app1/v1.1.3/z")

    def test_dirty_repo_blocks_everything(self):
        (self.pkg / "dev.txt").write_text("dirty")
        res = self.run_it()
        self.assertFalse(res["success"])
        self.assertFalse(res["changed"])
        self.assertEqual(self.head(self.app), "develop")

    def test_existing_in_some_repos_prompts_then_skips(self):
        git(self.app, "branch", "hotfix/v1.0.8/x")
        res = self.run_it()
        self.assertFalse(res["success"])
        self.assertTrue(res["alreadyExists"])
        self.assertEqual(res["existingRepos"], ["app1"])
        self.assertEqual(res["missingRepos"], ["pkg1"])
        self.assertEqual(self.head(self.pkg), "develop")
        res = self.run_it(skipExisting=True)
        self.assertTrue(res["success"], res)
        self.assertEqual(self.head(self.pkg), "hotfix/app1/v1.0.8/x")
        self.assertEqual(self.head(self.app), "develop")

    def test_existing_everywhere(self):
        git(self.app, "branch", "hotfix/v1.0.8/x")
        git(self.pkg, "branch", "hotfix/app1/v1.0.8/x")
        res = self.run_it(skipExisting=True)
        self.assertFalse(res["success"])
        self.assertEqual(res["missingRepos"], [])


if __name__ == "__main__":
    unittest.main()
