import os
import tempfile
import unittest
from pathlib import Path

from devgit import router
from devgit.core import workspaces


class SavedWorkspacesTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.TemporaryDirectory()
        self.ws = tempfile.TemporaryDirectory()
        self._old = os.environ.get("DEVGIT_CONFIG_DIR")
        os.environ["DEVGIT_CONFIG_DIR"] = self.cfg.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("DEVGIT_CONFIG_DIR", None)
        else:
            os.environ["DEVGIT_CONFIG_DIR"] = self._old
        self.cfg.cleanup()
        self.ws.cleanup()

    def test_empty_by_default(self):
        self.assertEqual(workspaces.list_workspaces(), [])

    def test_add_is_deduplicated_and_removable(self):
        workspaces.add_workspace(self.ws.name)
        workspaces.add_workspace(self.ws.name)
        items = workspaces.list_workspaces()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["exists"])
        workspaces.remove_workspace(self.ws.name)
        self.assertEqual(workspaces.list_workspaces(), [])

    def test_corrupt_file_is_ignored(self):
        (Path(self.cfg.name) / "workspaces.json").write_text("{nope")
        self.assertEqual(workspaces.list_workspaces(), [])

    def test_save_rejects_missing_dir(self):
        res = router.handle_workspace_save({"workspace": "/definitely/not/here"})
        self.assertFalse(res["success"])

    def test_save_and_remove_handlers(self):
        res = router.handle_workspace_save({"workspace": self.ws.name})
        self.assertTrue(res["success"])
        self.assertEqual(len(res["workspaces"]), 1)
        res = router.handle_workspace_remove({"workspace": self.ws.name})
        self.assertEqual(res["workspaces"], [])


if __name__ == "__main__":
    unittest.main()
