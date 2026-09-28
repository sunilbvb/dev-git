import os
import secrets
import logging
from typing import Optional

logger = logging.getLogger("devgit.auth")

# Global session token generated at server startup
SESSION_TOKEN: str = os.environ.get("DEVGIT_TOKEN") or secrets.token_hex(16)


def get_session_token() -> str:
    return SESSION_TOKEN


def set_session_token(token: str) -> None:
    global SESSION_TOKEN
    SESSION_TOKEN = token


def verify_token(provided_token: Optional[str]) -> bool:
    if not provided_token:
        return False
    return secrets.compare_digest(provided_token.strip(), SESSION_TOKEN)


def is_allowed_origin_or_host(host_header: Optional[str], origin_header: Optional[str]) -> bool:
    """
    Validate that requests come from localhost / 127.0.0.1 or the configured server host.
    Prevents cross-site request forgery / remote execution from arbitrary web pages.
    """
    allowed_hosts = {"localhost", "127.0.0.1", "[::1]"}
    
    if host_header:
        # Host might include port e.g. "127.0.0.1:8086"
        host_domain = host_header.split(":")[0].lower()
        if host_domain not in allowed_hosts and not host_domain.startswith("127."):
            logger.warning(f"Rejected request with host header: {host_header}")
            return False

    if origin_header:
        # Origin is e.g. "http://localhost:8086"
        if origin_header.strip().lower() == "null":
            logger.warning("Rejected request with null origin header")
            return False
        from urllib.parse import urlparse
        parsed = urlparse(origin_header)
        origin_domain = (parsed.hostname or "").lower()
        if origin_domain not in allowed_hosts and not origin_domain.startswith("127."):
            logger.warning(f"Rejected request with origin header: {origin_header}")
            return False

    return True
