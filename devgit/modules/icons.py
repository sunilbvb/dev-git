"""Restricted proxy for custom app icons.

Remote icons must be public http(s) images (no redirects, size-capped). Local icons
must be image files inside the workspace or workspace_assets directory.
"""
import ipaddress
import mimetypes
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

MAX_ICON_BYTES = 512 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}

Result = Tuple[int, str, bytes]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _fetch_remote(url: str) -> Result:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return 400, "text/plain", b"Invalid icon URL"
    if not _is_public_host(parsed.hostname):
        return 403, "text/plain", b"Icon host not allowed"
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "DevGit"}), timeout=5) as resp:
            ctype = (resp.headers.get_content_type() or "").lower()
            if not ctype.startswith("image/"):
                return 415, "text/plain", b"Not an image"
            data = resp.read(MAX_ICON_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return 502, "text/plain", b"Failed to fetch icon"
    if len(data) > MAX_ICON_BYTES:
        return 413, "text/plain", b"Icon too large"
    return 200, ctype, data


def _read_local(raw: str, allowed_roots: list) -> Result:
    path_str = raw
    if path_str.lower().startswith("file:"):
        path_str = urllib.parse.unquote(urllib.parse.urlparse(path_str).path)
    candidate = Path(path_str).expanduser()
    if not candidate.is_absolute():
        candidate = Path(allowed_roots[0]) / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return 404, "text/plain", b"Icon not found"
    if resolved.suffix.lower() not in IMAGE_EXTENSIONS:
        return 415, "text/plain", b"Not an image"
    if not any(resolved == r or r in resolved.parents for r in (Path(x).resolve() for x in allowed_roots)):
        return 403, "text/plain", b"Icon path not allowed"
    if not resolved.is_file():
        return 404, "text/plain", b"Icon not found"
    if resolved.stat().st_size > MAX_ICON_BYTES:
        return 413, "text/plain", b"Icon too large"
    ctype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    return 200, ctype, resolved.read_bytes()


def load_app_icon(raw_url: str, allowed_roots: list) -> Result:
    raw = (raw_url or "").strip()
    if not raw:
        return 400, "text/plain", b"url parameter is required"
    if raw.lower().startswith(("http://", "https://")):
        return _fetch_remote(raw)
    return _read_local(raw, allowed_roots)
