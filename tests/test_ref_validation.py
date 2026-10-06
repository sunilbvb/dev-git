import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from devgit.core.git import validate_ref
from devgit.modules import branches, release, stash


class TestRefValidation(unittest.TestCase):
    def test_validate_ref_rejections(self):
        invalid_refs = [
            "--exec=touch PWNED",
            "-d",
            "--output=/tmp/pwned",
            "branch; rm -rf /",
            "tag|cat",
            "stash`id`",
            "branch\nnewline",
            "../../etc/passwd",
            "../secret",
            "repo/../etc",
            "/etc/shadow",
            "feature//branch",
            " ",
            "",
            None
        ]
        for ref in invalid_refs:
            ok, reason = validate_ref(ref)
            self.assertFalse(ok, f"Ref '{ref}' should be rejected: {reason}")

    def test_validate_ref_allowed(self):
        valid_refs = [
            "main",
            "feature/login-page",
            "v1.0.0",
            "release-2.5",
            "stash@{0}",
            "HEAD~1",
            "HEAD~2..HEAD",
            "v1.0.0..v2.0.0",
        ]
        for ref in valid_refs:
            ok, reason = validate_ref(ref)
            self.assertTrue(ok, f"Ref '{ref}' should be allowed: {reason}")

    def test_branch_action_option_injection_prevented(self):
        res = branches.handle_git_branch_action({
            "repoPath": str(ROOT_DIR),
            "branchName": "--exec=touch PWNED",
            "action": "rebase"
        })
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid branchName", res.get("error", ""))

    def test_tag_compare_option_injection_prevented(self):
        res = release.handle_git_tags_compare({
            "repoPath": str(ROOT_DIR),
            "fromTag": "--output=/tmp/pwned",
            "toTag": "HEAD"
        })
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid fromTag", res.get("error", ""))

    def test_stash_apply_option_injection_prevented(self):
        res = stash.handle_git_stash_apply({
            "repoPath": str(ROOT_DIR),
            "stashRef": "--output=/tmp/pwned"
        })
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid stashRef", res.get("error", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
