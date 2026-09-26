#!/usr/bin/env python3
"""
Automated Unit Test Suite for DevGit Backend & Router.
Built with Python's standard library `unittest` (strict zero external dependencies).
"""

import os
import sys
import unittest
from pathlib import Path

# Add backend to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

import router


class TestDevGitRouter(unittest.TestCase):
    """Test core router functionality and git command dispatch."""

    @classmethod
    def setUpClass(cls):
        cls.workspace = ROOT_DIR
        router.set_workspace_root(cls.workspace)

    def test_workspace_root_setting(self):
        """Test workspace root getter and setter."""
        self.assertEqual(router.get_workspace_root().resolve(), self.workspace.resolve())

    def test_repo_discovery(self):
        """Test that dev-git repository itself is discovered in workspace."""
        repos = router._discover_git_repos(self.workspace)
        self.assertIsInstance(repos, list)
        self.assertTrue(len(repos) >= 1)
        self.assertTrue(any(r.resolve() == self.workspace.resolve() for r in repos))

    def test_git_repo_status_structure(self):
        """Test that _git_repo_status returns expected schema."""
        status = router._git_repo_status(self.workspace)
        self.assertIsInstance(status, dict)
        self.assertIn("name", status)
        self.assertIn("path", status)
        self.assertIn("branch", status)
        self.assertIn("dirty", status)
        self.assertIn("changes", status)
        self.assertIn("ahead", status)
        self.assertIn("behind", status)
        self.assertIn("conflict", status)
        self.assertIsInstance(status["conflict"], bool)
        self.assertIsInstance(status["dirty"], bool)
        self.assertIsInstance(status["ahead"], int)
        self.assertIsInstance(status["behind"], int)

    def test_serve_git_repos(self):
        """Test /api/git/repos endpoint handler."""
        res = router.serve_git_repos("/api/git/repos?refresh=true")
        self.assertTrue(res.get("success"))
        self.assertIn("repos", res)
        self.assertIsInstance(res["repos"], list)

    def test_serve_git_stashes(self):
        """Test /api/git/stashes endpoint handler."""
        # Missing repoPath
        bad_res = router.serve_git_stashes("/api/git/stashes")
        self.assertFalse(bad_res.get("success"))
        self.assertIn("error", bad_res)

        # Valid repoPath
        valid_res = router.serve_git_stashes(f"/api/git/stashes?repoPath={self.workspace}")
        self.assertTrue(valid_res.get("success"))
        self.assertIn("stashes", valid_res)
        self.assertIsInstance(valid_res["stashes"], list)

    def test_serve_git_conflicts(self):
        """Test /api/git/conflicts endpoint handler."""
        res = router.serve_git_conflicts(f"/api/git/conflicts?repoPath={self.workspace}")
        self.assertTrue(res.get("success"))
        self.assertIn("conflicts", res)
        self.assertIsInstance(res["conflicts"], list)

    def test_stash_pop_validation(self):
        """Test stash pop parameter validation."""
        res = router.handle_git_stash_pop({})
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error"), "Missing repoPath")

    def test_workspace_switch_validation(self):
        """Test workspace switch input validation."""
        # Missing path
        res1 = router.handle_workspace_switch({})
        self.assertFalse(res1.get("success"))
        self.assertIn("error", res1)

        # Non-existent path
        res2 = router.handle_workspace_switch({"workspacePath": "/non/existent/path/xyz_123"})
        self.assertFalse(res2.get("success"))
        self.assertIn("does not exist", res2.get("error", "").lower())

        # Valid path
        res3 = router.handle_workspace_switch({"workspacePath": str(self.workspace)})
        self.assertTrue(res3.get("success"))
        self.assertEqual(res3.get("workspaceRoot"), str(self.workspace))

    def test_branch_name_translation(self):
        """Test Melos multi-repo branch name translating logic."""
        # Standard branches stay identical
        self.assertEqual(router._translate_branch_name("main", "app1", True), "main")
        self.assertEqual(router._translate_branch_name("develop", "app1", True), "develop")

        # Custom branch
        translated = router._translate_branch_name("feat/login", "all", False)
        self.assertEqual(translated, "feat/login")


if __name__ == "__main__":
    unittest.main(verbosity=2)
