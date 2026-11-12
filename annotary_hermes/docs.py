"""What the plugin records per Document (editor, sharing session) and reads from Annotary."""

from __future__ import annotations

import time
from pathlib import Path

from . import accounts, enablement, server, state


#: Which Hermes process holds a session, and so can wake it: the gateway (messaging chats and its
#: local sessions) or the dashboard's Desktop backend (Desktop chats a remote Hermes hosts there).
GATEWAY, DESKTOP = "gateway", "desktop"


def record_share(doc: str, *, name: str, profile: str, session_key: str, surface: str, path: str,
                 host: str = GATEWAY, root: Path | None = None) -> None:
    def work(st: dict) -> None:
        st["docs"][doc] = {"name": name, "editor": profile, "session_key": session_key,
                           "surface": surface, "host": host, "path": path, "shared_at": time.time()}
    state.update(work, root)


def info(doc: str, root: Path | None = None) -> dict | None:
    return state.load(root)["docs"].get(doc)


def set_editor(doc: str, profile: str, *, session_key: str = "", host: str = GATEWAY,
               root: Path | None = None) -> dict:
    def work(st: dict) -> dict:
        entry = st["docs"].setdefault(doc, {})
        entry["editor"] = profile
        key, where = session_key, host
        if not key:
            last = st["sessions"].get(profile, {})
            key, where = last.get("session_key", ""), last.get("host") or GATEWAY
        entry["session_key"], entry["host"] = key, where
        entry["handed_off_at"] = time.time()
        return dict(entry)
    return state.update(work, root)


def set_editor_for_handle(doc: str, handle: str, root: Path | None = None) -> dict:
    """Hand *doc* to the Bot with *handle* (the page's editor picker). Only an enabled Member."""
    pid = accounts.active_handles(root).get((handle or "").lstrip("@").strip())
    if not pid:
        raise ValueError("not an active Bot of this Hermes install")
    if not enablement.has_annotary(enablement.plugin_state(pid, root)):
        raise ValueError(f"Annotary is off in that Bot's profile; turn it on with `{enablement.turn_on(pid)}`")
    return set_editor(doc, pid, root=root)


def read_threads(token: str, doc_id: str, *, open_only: bool = True) -> list[dict]:
    """A Document's Threads with every reply's body (``thread list`` has only the root's)."""
    raw = server.api(token, "GET", f"/api/v1/docs/{doc_id}/threads?status={'open' if open_only else 'all'}")
    who = server.person_handle
    out = []
    for t in raw.get("threads") or []:
        if t.get("deleted"):
            continue
        anchor = t.get("anchor") or {}
        cur, orig = anchor.get("current") or {}, anchor.get("original") or {}
        out.append({
            "id": t.get("id"), "author": who(t.get("author")), "body": t.get("body"),
            "where": (f"v{cur.get('version')}:{cur.get('range')} ({cur.get('status')}) \"{orig.get('exact', '')}\""
                      if cur.get("range") else t.get("subject") or "document"),
            "resolved": bool(t.get("resolved")),
            "replies": [{"id": r.get("id"), "author": who(r.get("author")), "body": r.get("body")}
                        for r in t.get("replies") or [] if not r.get("deleted")],
        })
    return out


def note_session(profile: str, session_key: str, surface: str, host: str = GATEWAY,
                 root: Path | None = None) -> None:
    """Remember the session a profile last used Annotary from (where an @mention wakes it)."""
    if not session_key:
        return
    def work(st: dict) -> None:
        st["sessions"][profile] = {"session_key": session_key, "surface": surface, "host": host,
                                   "at": time.time()}
    state.update(work, root)


def doc_events(doc: str, root: Path | None = None) -> list[dict]:
    """Every event of one Document, oldest first (owner view)."""
    tok = server.owner_token(root)
    out: list[dict] = []
    since = 0
    while True:
        page = server.api(tok, "GET", f"/api/v1/events?since={since}&doc={doc}&limit=1000")
        out.extend(page.get("events") or [])
        if not page.get("events") or int(page.get("seq") or 0) <= since:
            return out
        since = int(page["seq"])


def resolve_id(doc: str, token: str, root: Path | None = None) -> dict:
    """``show DOC --json`` as the caller: the Document's id, name, Version and Actions."""
    import json
    r = server.run_cli(token, ["show", doc, "--json"], root=root)
    if r.returncode != 0:
        raise server.ServerError(r.stderr.strip()[-300:] or f"no Document {doc}")
    return json.loads(r.stdout)


def review_is_open(doc_id: str, root: Path | None = None) -> bool:
    from . import rules
    return rules.review_open(doc_events(doc_id, root), managed=accounts.handles(root))
