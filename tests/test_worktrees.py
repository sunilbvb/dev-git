import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

import devgit.router as router
from devgit.modules import worktrees
from devgit.core.git import git_repo_status, run_git


class TestGitWorktrees(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = ROOT_DIR
        router.set_workspace_root(cls.workspace)
        cls.temp_dir = tempfile.mkdtemp(prefix="devgit_wt_test_")

    @classmethod
    def tearDownClass(cls):
        # Prune and remove any leftovers
        try:
            worktrees.handle_git_worktree_prune({"repoPath": str(cls.workspace)})
        except Exception:
            pass
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_list_main_worktree(self):
        res = router.serve_git_worktrees(f"/api/git/worktrees?repoPath={self.workspace}")
        self.assertTrue(res.get("success"))
        self.assertIn("worktrees", res)
        wts = res["worktrees"]
        self.assertTrue(len(wts) >= 1)
        main_wt = wts[0]
        self.assertTrue(main_wt.get("isMain"))
        self.assertEqual(Path(main_wt.get("path")).resolve(), self.workspace.resolve())
        self.assertTrue(main_wt.get("head"))
        self.assertTrue(main_wt.get("branch"))

    def test_worktree_lifecycle_add_status_remove(self):
        wt_target_path = Path(self.temp_dir) / "test-feature-wt"
        branch_name = "test-wt-temp-branch"

        # Ensure branch is cleaned up beforehand
        run_git(self.workspace, ["branch", "-D", branch_name])

        try:
            # 1. Add worktree
            add_res = router.handle_git_worktree_add({
                "repoPath": str(self.workspace),
                "worktreePath": str(wt_target_path),
                "branch": branch_name,
                "newBranch": True
            })
            self.assertTrue(add_res.get("success"), f"Add failed: {add_res.get('error')}")
            self.assertTrue(wt_target_path.exists())
            self.assertTrue((wt_target_path / ".git").is_file())

            # 2. Check worktree list reflects the new worktree
            list_res = router.serve_git_worktrees(f"/api/git/worktrees?repoPath={self.workspace}")
            self.assertTrue(list_res.get("success"))
            paths = [Path(w["path"]).resolve() for w in list_res["worktrees"]]
            self.assertIn(wt_target_path.resolve(), paths)

            # 3. Check git_repo_status detects worktrees
            main_status = git_repo_status(self.workspace)
            self.assertFalse(main_status.get("isWorktree"))
            self.assertGreaterEqual(main_status.get("worktreeCount", 0), 2)

            wt_status = git_repo_status(wt_target_path)
            self.assertTrue(wt_status.get("isWorktree"))
            self.assertEqual(wt_status.get("branch"), branch_name)
            self.assertEqual(Path(wt_status.get("mainWorktree")).resolve(), self.workspace.resolve())

            # 4. Attempt to remove main worktree (must be rejected)
            fail_remove = router.handle_git_worktree_remove({
                "repoPath": str(self.workspace),
                "worktreePath": str(self.workspace),
            })
            self.assertFalse(fail_remove.get("success"))
            self.assertIn("main", fail_remove.get("error", "").lower())

            # 5. Remove linked worktree
            rem_res = router.handle_git_worktree_remove({
                "repoPath": str(self.workspace),
                "worktreePath": str(wt_target_path),
                "force": True
            })
            self.assertTrue(rem_res.get("success"), f"Remove failed: {rem_res.get('error')}")
            self.assertFalse(wt_target_path.exists())

            # 6. Prune
            prune_res = router.handle_git_worktree_prune({"repoPath": str(self.workspace)})
            self.assertTrue(prune_res.get("success"))

        finally:
            run_git(self.workspace, ["worktree", "remove", "--force", str(wt_target_path)])
            run_git(self.workspace, ["branch", "-D", branch_name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
