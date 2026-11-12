"""The Webapp's address, and the web link to a Document's Annotary page.

The link carries the Document in the query only, `?annotary=ID`, which the page script reads
(`desktop/plugin.js`, `linkedDoc`) and opens once the page registers. Never add the page's route
(`#/annotary?doc=ID`): on a cold load the Webapp reads it as a chat id before plugins load, so the
page never loads. A server-side sign-in keeps the query and drops any fragment anyway.
"""

from __future__ import annotations

import ipaddress
import urllib.parse

from . import accounts, paths

#: The query parameter the page reads. Must match `LINK_PARAM` in `desktop/plugin.js`.
LINK_PARAM = "annotary"


def _config() -> dict:
    """The Hermes root's config. In the root's own process, Hermes's merged config (managed overlay,
    `${ENV}` expansion), which Hermes Cloud uses for `public_url`; otherwise the file as written."""
    root = paths.hermes_root()
    try:
        from hermes_cli.config import load_config_readonly
        own = root.resolve() == paths.current_home().resolve()
    except (ImportError, OSError):  # not running inside Hermes
        own = False
    if own:
        conf = load_config_readonly()
        return conf if isinstance(conf, dict) else {}
    return accounts._read_profile_yaml(root / "config.yaml")


def _public_url(value) -> str | None:
    """`public_url` without a trailing slash; "" when unset; None when Hermes would reject it (not an
    http(s) address with a host, or one carrying credentials, a query or a fragment)."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or any(c in value for c in "\"'<> \t\r\n?#@\\"):
        return None
    url = value.rstrip("/")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port  # a malformed port raises
    except ValueError:
        return None
    return url if parts.scheme in {"http", "https"} and parts.hostname and port != 0 else None


def _host_ok(value) -> bool:
    """A bind Hermes accepts: local-only (127.0.0.1, ::1, localhost) or a wildcard (0.0.0.0, ::)."""
    if not isinstance(value, str):
        return False
    host = value.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        host = ipaddress.ip_address(host).compressed
    except ValueError:
        host = host.lower()
    return host in {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}


def settings() -> tuple[bool, str]:
    """(turned on, public address), read as Hermes reads them: on only for `enabled: true` with a
    usable host, port and address; "" for an address it would not use. Public config reads only,
    so a Hermes release that moves its internals cannot break it."""
    conf = _config().get("webapp")
    if not isinstance(conf, dict):
        return False, ""
    public = _public_url(conf.get("public_url"))
    port = conf.get("port", 9120)
    port_ok = isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
    usable = _host_ok(conf.get("host", "127.0.0.1")) and port_ok and public is not None
    return conf.get("enabled") is True and usable, public or ""


def doc_url(doc: str, public: str | None = None) -> str | None:
    """The Document's page in the Webapp at *public* (default: `webapp.public_url`), or None
    when no public address is set."""
    if public is None:
        public = settings()[1]
    public = (public or "").rstrip("/")
    if not public:
        return None
    return f"{public}/?{urllib.parse.urlencode({LINK_PARAM: doc})}"
