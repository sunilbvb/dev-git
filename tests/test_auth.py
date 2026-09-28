import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

import router
from core import auth


class TestDevGitAuth(unittest.TestCase):
    def setUp(self):
        auth.set_session_token("test-secret-token-12345")

    def test_token_verification(self):
        self.assertTrue(auth.verify_token("test-secret-token-12345"))
        self.assertFalse(auth.verify_token("wrong-token"))
        self.assertFalse(auth.verify_token(None))
        self.assertFalse(auth.verify_token(""))

    def test_allowed_origin_and_host(self):
        # Valid host and origins
        self.assertTrue(auth.is_allowed_origin_or_host("localhost:8086", "http://localhost:8086"))
        self.assertTrue(auth.is_allowed_origin_or_host("127.0.0.1:8086", "http://127.0.0.1:8086"))
        self.assertTrue(auth.is_allowed_origin_or_host(None, None))
        
        # Invalid / Malicious external origin or host
        self.assertFalse(auth.is_allowed_origin_or_host("attacker.com", "http://attacker.com"))
        self.assertFalse(auth.is_allowed_origin_or_host("localhost:8086", "http://evil.com"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
