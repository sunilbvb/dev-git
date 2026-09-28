import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from modules.terminal import validate_git_terminal_args, handle_git_terminal_run


class TestTerminalSecurity(unittest.TestCase):
    def test_allowed_subcommands(self):
        valid_commands = [
            ["status"],
            ["log", "-n", "10"],
            ["diff"],
            ["branch", "-a"],
            ["checkout", "main"],
            ["stash", "list"],
        ]
        for cmd in valid_commands:
            ok, reason = validate_git_terminal_args(cmd)
            self.assertTrue(ok, f"Command {cmd} should be allowed: {reason}")

    def test_forbidden_subcommands(self):
        invalid_commands = [
            ["config", "user.name", "hacker"],
            ["alias", "x", "!calc.exe"],
            ["format-patch", "HEAD~1"],
            ["fast-import"],
        ]
        for cmd in invalid_commands:
            ok, reason = validate_git_terminal_args(cmd)
            self.assertFalse(ok, f"Subcommand {cmd[0]} should be forbidden")

    def test_forbidden_flags(self):
        dangerous_flags = [
            ["status", "-c", "core.sshCommand=calc"],
            ["log", "--config", "alias.x=!cmd"],
            ["diff", "--exec-path=/tmp"],
            ["branch", "-c=foo"],
            ["checkout", "; rm -rf /"],
            ["rebase", "-x", "touch /tmp/pwn"],
            ["rebase", "-xid"],
            ["rebase", "--exec", "cat /etc/passwd"],
            ["rebase", "--exec=whoami"],
            ["log", "--output=/tmp/evil.txt"],
            ["log", "--output", "/tmp/evil.txt"],
            ["diff", "--output=/tmp/evil.txt"],
        ]
        for cmd in dangerous_flags:
            ok, reason = validate_git_terminal_args(cmd)
            self.assertFalse(ok, f"Command {cmd} with dangerous flag should be rejected: {reason}")

    def test_handle_git_terminal_run_rejection(self):
        res = handle_git_terminal_run({
            "repoPath": str(ROOT_DIR),
            "command": "git -c core.sshCommand=calc status"
        })
        self.assertFalse(res.get("success"))
        self.assertIn("Security restriction", res.get("error", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
