import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))


class TestServerStartup(unittest.TestCase):
    def test_import_server(self):
        """Verify that server and all dependencies import without NameError or startup crash."""
        import server
        self.assertIsNotNone(server.GitHandler)
        self.assertIsNotNone(server.router)

    def test_import_modules(self):
        """Verify that all backend modules can be imported directly."""
        from modules import terminal, branches, commits, stash, release, ai
        self.assertTrue(callable(terminal.validate_git_terminal_args))
        self.assertTrue(callable(branches.handle_git_branch_action))


if __name__ == "__main__":
    unittest.main(verbosity=2)
