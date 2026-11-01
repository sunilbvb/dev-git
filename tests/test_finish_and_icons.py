import subprocess
import tempfile
import unittest
from pathlib import Path

from devgit import router
from devgit.modules.icons import load_app_icon


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class BranchFinishTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(router.set_workspace_root, router.get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.remote = root / "remote.git"
        self.ws = root / "ws"
        self.repo = self.ws / "app"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(self.repo, "init", "-q", "-b", "develop")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "a.txt").write_text("a")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "develop")
        git(self.repo, "checkout", "-qb", "feature/x")
        (self.repo / "b.txt").write_text("b")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "feat")
        git(self.repo, "push", "-q", "origin", "feature/x")
        router.set_workspace_root(self.ws)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finish_merges_and_deletes(self):
        res = router.handle_git_branch_finish(
            {"repoPath": str(self.repo), "branchName": "feature/x", "baseBranch": "develop"})
        self.assertTrue(res["success"], res)
        branches = subprocess.run(["git", "-C", str(self.repo), "branch"], capture_output=True, text=True).stdout
        self.assertNotIn("feature/x", branches)
        self.assertTrue((self.repo / "b.txt").exists())
        remote = subprocess.run(["git", "-C", str(self.remote), "branch"], capture_output=True, text=True).stdout
        self.assertNotIn("feature/x", remote)

    def test_finish_rejects_bad_input(self):
        self.assertFalse(router.handle_git_branch_finish({"repoPath": str(self.repo)})["success"])
        bad = router.handle_git_branch_finish(
            {"repoPath": str(self.repo), "branchName": "--force", "baseBranch": "develop"})
        self.assertFalse(bad["success"])
        unknown = router.handle_git_branch_finish(
            {"repoPath": "/tmp", "branchName": "feature/x", "baseBranch": "develop"})
        self.assertFalse(unknown["success"])


class IconProxyTest(unittest.TestCase):
    def test_local_inside_root_ok_and_outside_denied(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            (Path(d) / "i.png").write_bytes(b"\x89PNG")
            (Path(other) / "i.png").write_bytes(b"\x89PNG")
            (Path(d) / "secret.txt").write_text("x")
            self.assertEqual(load_app_icon("i.png", [d])[0], 200)
            self.assertEqual(load_app_icon(str(Path(other) / "i.png"), [d])[0], 403)
            self.assertEqual(load_app_icon("secret.txt", [d])[0], 415)
            self.assertEqual(load_app_icon("../x.png", [d])[0], 403)

    def test_remote_private_hosts_blocked(self):
        self.assertEqual(load_app_icon("http://127.0.0.1:8086/x.png", ["."])[0], 403)
        self.assertEqual(load_app_icon("http://localhost/x.png", ["."])[0], 403)
        self.assertEqual(load_app_icon("", ["."])[0], 400)


class TagsTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(router.set_workspace_root, router.get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.remote = root / "remote.git"
        self.ws = root / "ws"
        self.repo = self.ws / "app"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "a.txt").write_text("a")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "tag", "-a", "v1.0.0", "-m", "first release")
        router.set_workspace_root(self.ws)
        self.args = {"repoPath": str(self.repo)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_has_version_and_pushed(self):
        tag = router.handle_git_tags_list(self.args)["tags"][0]
        self.assertEqual(tag["version"], "v1.0.0")
        self.assertEqual(tag["message"], "first release")
        self.assertFalse(tag["pushed"])

    def test_push_all_then_listed_as_pushed(self):
        self.assertTrue(router.handle_git_tag_push(self.args)["success"])
        self.assertTrue(router.handle_git_tags_list(self.args)["tags"][0]["pushed"])

    def test_push_single_by_version(self):
        self.assertTrue(router.handle_git_tag_push({**self.args, "version": "v1.0.0"})["success"])
        self.assertFalse(router.handle_git_tag_push({**self.args, "version": "nope"})["success"])

    def test_edit_renames_and_updates_message(self):
        res = router.handle_git_tag_edit(
            {**self.args, "oldVersion": "v1.0.0", "newVersion": "1.0.1", "message": "renamed"})
        self.assertTrue(res["success"], res)
        tag = router.handle_git_tags_list(self.args)["tags"][0]
        self.assertEqual((tag["version"], tag["message"]), ("v1.0.1", "renamed"))

    def test_delete_by_version(self):
        self.assertTrue(router.handle_git_tag_delete({**self.args, "version": "v1.0.0"})["success"])
        self.assertEqual(router.handle_git_tags_list(self.args)["tags"], [])
        self.assertFalse(router.handle_git_tag_delete({**self.args, "version": "v1.0.0"})["success"])

    def test_create_defaults_to_pubspec_and_pushes(self):
        (self.repo / "pubspec.yaml").write_text("name: x\nversion: 2.3.4+5\n")
        res = router.handle_git_tag_create({**self.args, "tagName": "", "message": "rel", "pushToRemote": True})
        self.assertTrue(res["success"], res)
        self.assertEqual(res["tagName"], "v2.3.4+5")
        self.assertTrue(res["pushed"])
        again = router.handle_git_tag_create({**self.args, "tagName": "v2.3.4+5", "message": "rel"})
        self.assertTrue(again.get("skipped"))


def _out(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


class BranchActionsTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(router.set_workspace_root, router.get_workspace_root())
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.remote = root / "remote.git"
        self.ws = root / "ws"
        self.repo = self.ws / "app"
        self.repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        git(self.repo, "init", "-q", "-b", "develop")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "a.txt").write_text("a")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "develop")
        git(self.repo, "checkout", "-qb", "feature/x")
        (self.repo / "b.txt").write_text("b")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "feat")
        git(self.repo, "push", "-q", "origin", "feature/x")
        git(self.repo, "checkout", "-q", "develop")
        router.set_workspace_root(self.ws)
        self.base = {"repoPath": str(self.repo)}

    def tearDown(self):
        self.tmp.cleanup()

    def act(self, action, branch, **extra):
        return router.handle_git_branch_action({**self.base, "action": action, "branch": branch, **extra})

    def test_checkout_switches_branch_and_prompts_when_missing(self):
        self.assertTrue(self.act("checkout", "feature/x")["success"])
        self.assertEqual(_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "feature/x")
        prompt = self.act("checkout", "nope")
        self.assertTrue(prompt.get("prompt"))
        made = self.act("checkout", "nope", createMissingMap={"app": True})
        self.assertTrue(made["success"], made)

    def test_merge_into_target_and_push(self):
        res = self.act("merge", "feature/x", targetBranch="develop")
        self.assertTrue(res["success"], res)
        self.assertEqual(_out(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "develop")
        self.assertTrue((self.repo / "b.txt").exists())
        self.assertIn("b.txt", _out(self.remote, "ls-tree", "-r", "--name-only", "develop"))

    def test_rename_local_and_remote(self):
        res = self.act("rename", "feature/x", newBranch="feature/y", remote=True)
        self.assertTrue(res["success"], res)
        self.assertIn("feature/y", _out(self.repo, "branch"))
        remote_branches = _out(self.remote, "branch")
        self.assertIn("feature/y", remote_branches)
        self.assertNotIn("feature/x", remote_branches)

    def test_fetch_pull_push(self):
        self.assertTrue(self.act("fetch", "develop")["success"])
        self.assertTrue(self.act("pull", "develop")["success"])
        self.assertTrue(self.act("push", "develop")["success"])

    def test_dirty_tree_blocks_actions(self):
        (self.repo / "a.txt").write_text("changed")
        res = self.act("checkout", "feature/x")
        self.assertFalse(res["success"])
        self.assertTrue(res.get("dirty"))

    def test_bad_input_rejected(self):
        self.assertFalse(self.act("checkout", "--force")["success"])
        self.assertFalse(self.act("explode", "develop")["success"])
        self.assertFalse(self.act("merge", "develop", targetBranch="develop")["success"])


if __name__ == "__main__":
    unittest.main()
