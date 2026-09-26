#!/usr/bin/env python3
"""
Unit tests for repository discovery strategies in DevGit.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add backend to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

import router


class TestDiscoveryStrategy(unittest.TestCase):
    """Test monorepo discovery, .devgit.json parsing, and fallback scans."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_single_repo_discovery(self):
        """Test discovering a single repository."""
        git_dir = self.workspace / ".git"
        git_dir.mkdir()
        
        repos = router._discover_git_repos(self.workspace)
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].resolve(), self.workspace.resolve())

    def test_multi_repo_subdirectories(self):
        """Test discovering repos in apps/ and packages/."""
        app1 = self.workspace / "apps" / "my_app"
        app1.mkdir(parents=True)
        (app1 / ".git").mkdir()

        pkg1 = self.workspace / "packages" / "my_pkg"
        pkg1.mkdir(parents=True)
        (pkg1 / ".git").mkdir()

        repos = router._discover_git_repos(self.workspace)
        repo_names = {r.name for r in repos}
        self.assertIn("my_app", repo_names)
        self.assertIn("my_pkg", repo_names)

    def test_devgit_json_custom_layout(self):
        """Test discovering repos using custom .devgit.json configuration."""
        svc1 = self.workspace / "services" / "auth_svc"
        svc1.mkdir(parents=True)
        (svc1 / ".git").mkdir()

        config_path = self.workspace / ".devgit.json"
        config_path.write_text('{"include": ["services"]}', encoding="utf-8")

        repos = router._discover_git_repos(self.workspace)
        repo_names = {r.name for r in repos}
        self.assertIn("auth_svc", repo_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
