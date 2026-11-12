"""The Webapp's address, and the web link to a Document's Annotary page.

The link carries the Document in the query only, `?annotary=ID`, which the page script reads
(`desktop/plugin.js`, `linkedDoc`) and opens once the page registers. Never add the page's route
(`#/annotary?doc=ID`): on a cold load the Webapp reads it as a chat id before plugins load, so the
page never loads. A server-side sign-in keeps the query and drops any fragment anyway.
"""

from __future__ import annotations

import re
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
    """`public_url` without a trailing slash; "" when unset; None when Hermes would reject it."""
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"https?://[^\s/?#@\\\"'<>]+(/[^\s?#@\\\"'<>]*)?", value):
        return None
    try:
        port = urllib.parse.urlsplit(value).port  # a malformed port raises
    except ValueError:
        return None
    return None if port == 0 else value.rstrip("/")


def settings() -> tuple[bool, str]:
    """(turned on, public address), read as Hermes reads them: on only for `enabled: true` with a
    usable port and address; "" for an address it would not use. Public config reads only, so a
    Hermes release that moves its internals cannot break it."""
    conf = _config().get("webapp")
    if not isinstance(conf, dict):
        return False, ""
    public = _public_url(conf.get("public_url"))
    port = conf.get("port", 1)
    port_ok = isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
    return conf.get("enabled") is True and port_ok and public is not None, public or ""


def doc_url(doc: str, public: str | None = None) -> str | None:
    """The Document's page in the Webapp at *public* (default: `webapp.public_url`), or None
    when no public address is set."""
    if public is None:
        public = settings()[1]
    public = (public or "").rstrip("/")
    if not public:
        return None
    return f"{public}/?{urllib.parse.urlencode({LINK_PARAM: doc})}"
