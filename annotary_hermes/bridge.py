"""The backend half of Annotary's embed protocol (version 1): the shell, and one HTTP request.

The page shows Annotary's own server-rendered pages in a sandboxed frame with an opaque origin;
the frame sends each request over postMessage to the page, the page to this backend (through
Hermes's own sign-in), and this module to the private server as the owner. Annotary's spec:
``docs/dev/web-document-view.md``, "Embed mode".
"""

from __future__ import annotations

import base64
import http.client
import urllib.error
import urllib.request
from pathlib import Path

from . import paths, server

PROTOCOL = 1
#: Request headers the frame may pass on (the spec's list); everything else is dropped.
FORWARD = {"content-type", "accept", "x-annotary-tz", "x-annotary-hc", "x-annotary-part", "x-annotary-etag"}
#: Response headers the frame never needs (cookies would not reach an opaque origin anyway).
DROP = {"set-cookie", "connection", "keep-alive", "transfer-encoding", "content-length"}
#: Largest answer carried through Hermes's bridge. Above about 1 MB a message stalls the gateway
#: (measured in the spike), so a bigger answer is refused with 413: the frame then shows the
#: Asset's "Open" button. Binary answers travel as base64 (a third larger), so their cap is 750 KB,
#: above Annotary's embed image limit (700 KiB); Annotary splits pages over 384 KiB into parts.
MAX_BYTES = 1_000_000
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # the frame follows redirects itself
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _send(method: str, path: str, headers: dict, data: bytes | None, timeout: float):
    req = urllib.request.Request(paths.server_url() + path, data=data, method=method, headers=headers)
    try:
        r = _opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:  # 3xx (not followed), 4xx, 5xx: an answer all the same
        r = e
    return r.status if hasattr(r, "status") else r.code, r.headers, r.read(MAX_BYTES + 1)


def shell(root: Path | None = None) -> str | None:
    """Annotary's frame shell (``/embed/shell``), or None when this server has no embed mode."""
    try:
        status, headers, body = _send("GET", "/embed/shell", {"Authorization": f"Bearer {server.owner_token(root)}"},
                                      None, 15)
    except (urllib.error.URLError, OSError):
        return None
    if status != 200 or "html" not in (headers.get("content-type") or ""):
        return None
    return body.decode("utf-8", "replace")


def request(msg: dict, root: Path | None = None, timeout: float = 60) -> dict:
    """Answer one ``annotary-req`` as the ``annotary-res`` fields (status, headers, body, encoding)."""
    method = str(msg.get("method") or "GET").upper()
    path = msg.get("path")
    if method not in METHODS or not isinstance(path, str) or not path.startswith("/") or path.startswith("//") \
            or any(c in path for c in "\r\n\\") or "://" in path:
        return {"status": 400, "headers": {"content-type": "text/plain"}, "body": "bad bridge request"}
    headers = {k.title(): str(v) for k, v in (msg.get("headers") or {}).items()
               if isinstance(k, str) and k.lower() in FORWARD and isinstance(v, (str, int))}
    headers["Authorization"] = f"Bearer {server.owner_token(root)}"
    headers["X-Annotary-Embed"] = "1"
    body = msg.get("body")
    data = body.encode("utf-8") if isinstance(body, str) and method not in ("GET", "HEAD") else None
    try:
        status, rh, raw = _send(method, path, headers, data, timeout)
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return {"status": 0, "headers": {}, "body": ""}
    out_headers = {k.lower(): v for k, v in rh.items() if k.lower() not in DROP}
    if len(raw) > (MAX_BYTES * 3 // 4 if msg.get("binary") else MAX_BYTES):  # base64 grows by a third
        return {"status": 413, "headers": {"content-type": "text/plain"},
                "body": "too large for the Hermes bridge; open it outside"}
    if msg.get("binary"):
        return {"status": status, "headers": out_headers, "body": base64.b64encode(raw).decode("ascii"),
                "encoding": "base64"}
    return {"status": status, "headers": out_headers, "body": raw.decode("utf-8", "replace")}
