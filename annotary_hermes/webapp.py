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


def settings() -> tuple[bool, str]:
    """(turned on, public address), read as Hermes reads them; "" for an address it would not use."""
    root = paths.hermes_root()
    try:
        from gateway.webapp_listener import webapp_settings
    except ImportError:  # not running inside Hermes
        conf = accounts._read_profile_yaml(root / "config.yaml").get("webapp")
        conf = conf if isinstance(conf, dict) else {}
        public = conf.get("public_url")
        valid = isinstance(public, str) and re.fullmatch(r"https?://[^\s/?#@]+(/[^\s?#@]*)?", public)
        return conf.get("enabled") is True, public.rstrip("/") if valid else ""
    s = webapp_settings(root)
    return s.enabled is True, (s.public_url or "").rstrip("/")


def doc_url(doc: str, public: str | None = None) -> str | None:
    """The Document's page in the Webapp at *public* (default: `webapp.public_url`), or None
    when no public address is set."""
    if public is None:
        public = settings()[1]
    public = (public or "").rstrip("/")
    if not public:
        return None
    return f"{public}/?{urllib.parse.urlencode({LINK_PARAM: doc})}"
