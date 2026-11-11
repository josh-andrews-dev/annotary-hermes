"""Annotary page backend, mounted at /api/plugins/annotary/ behind Hermes's own sign-in.

The page reaches the private server only through these routes (they act as the owner), so it
works from every surface: native Desktop, Desktop over SSH, the Webapp on a phone.

    GET  /status             server, wake-ups, whether the server has embed mode
    POST /seen               the page registered (Desktop, or a browser where it is on)
    GET  /documents          the Document list, with each Document's editor
    GET  /doc?id=ID          one Document: header, rendered HTML, open Threads, Actions, editor
    POST /act      {doc, action}
    POST /comment  {doc, text}               a Comment on the whole Document
    POST /reply    {doc, thread, text, resolve?}
    POST /resolve  {doc, thread}
    POST /editor   {doc, to}                 hand the Document to another Bot (D11)
    GET  /shell              the embed-mode frame shell (when the server has embed mode)
    POST /proxy    {method, path, headers, body, binary?}   one frame request (embed protocol v1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

_PLUGIN = Path(__file__).resolve().parents[1]
if str(_PLUGIN) not in sys.path:
    sys.path.insert(0, str(_PLUGIN))

from annotary_hermes import accounts, bridge, desktop, enablement, paths, server, state, tools  # noqa: E402

log = logging.getLogger("annotary_hermes")
router = APIRouter()
DOC_ID = re.compile(r"^[a-z0-9]{1,16}$")
THREAD_ID = re.compile(r"^t\d{1,6}$")
MAX_BRIDGE_BYTES = 1_000_000  # the frame bridge stalls the gateway above about 1 MB


def _owner() -> str:
    server.ensure_running()
    try:
        accounts.reconcile_if_due()
    except server.ServerError:
        pass
    return server.owner_token()


def _doc_id(value) -> str:
    if not isinstance(value, str) or not DOC_ID.match(value):
        raise HTTPException(400, "bad document id")
    return value


def _cli(args: list[str], stdin: str | None = None) -> dict:
    r = server.run_cli(_owner(), [*args, "--json"], stdin=stdin)
    if r.returncode != 0:
        raise HTTPException(409 if r.returncode == 5 else 400, (r.stderr.strip() or "failed")[-300:])
    try:
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        return {}


def _raw(path: str) -> tuple[int, str, bytes]:
    req = urllib.request.Request(paths.server_url() + path, headers={"Authorization": f"Bearer {_owner()}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("content-type", ""), r.read(MAX_BRIDGE_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read(MAX_BRIDGE_BYTES + 1)


def _editor_view(st: dict, doc: str) -> dict:
    entry = st["docs"].get(doc) or {}
    pid = entry.get("editor")
    handle = st["members"].get(pid, {}).get("handle") if pid else None
    return {"editor": f"@{handle}" if handle else None, "editor_profile": pid}


def _wake_on() -> bool:
    try:
        from hermes_cli.config import load_config_readonly
        entry = (((load_config_readonly() or {}).get("plugins") or {}).get("entries") or {}).get(paths.PLUGIN_ID) or {}
        return entry.get("allow_gateway_injection") is True
    except Exception:  # noqa: BLE001
        return False


def _status() -> dict:
    server.ensure_running()
    try:  # an earlier version's standalone page calls this first; once it is gone, a reload loads the half
        desktop.retire_standalone_page()
    except OSError as e:
        log.warning("annotary: could not remove the old standalone desktop page: %s", e)
    st = state.load()
    return {"ok": True, "server": server.health(), "embed": bridge.shell() is not None, "wake": _wake_on(),
            "owner": "@" + server.owner_handle(),
            "bots": sorted("@" + m["handle"] for pid, m in st["members"].items() if not m.get("disabled")
                           and enablement.has_annotary(enablement.plugin_state(pid)))}


@router.get("/status")
async def status():
    return await asyncio.to_thread(_status)


@router.post("/seen")
async def seen():
    await asyncio.to_thread(tools.record_page_seen)
    return {"ok": True}


def _current_action(d: dict) -> dict | None:
    """The head Version's Action (id, label, by), so the page can say what happened, not the button's label."""
    a = d.get("action") or {}
    return {k: a.get(k) for k in ("id", "label", "by")} if a and a.get("version") == d["version"] else None


def _docs() -> dict:
    tok = _owner()
    rows = server.api(tok, "GET", "/api/v1/docs").get("docs", [])
    st = state.load()
    return {"docs": [{"id": d["id"], "name": d["name"], "title": d.get("title") or d["name"], "version": d["version"],
                      "open": d.get("open_threads", 0), "updated": d.get("updated_at"),
                      "action": _current_action(d),
                      **_editor_view(st, d["id"])} for d in rows]}


@router.get("/documents")  # not /docs: a non-default profile's plugin host would serve FastAPI's Swagger page there
async def docs():
    return await asyncio.to_thread(_docs)


def _doc(doc: str) -> dict:
    tok = _owner()
    head = server.api(tok, "GET", f"/api/v1/docs/{doc}")
    threads = server.api(tok, "GET", f"/api/v1/docs/{doc}/threads").get("threads", [])
    code, _, html = _raw(f"/api/v1/docs/{doc}/versions/{head['version']}/html")
    action = head.get("action") or {}
    return {
        "id": head["id"], "name": head["name"], "version": head["version"], "by": head.get("by"),
        "message": head.get("message"), "at": head.get("at"),
        "action": action if action.get("version") == head["version"] else None,
        "actions": head.get("available_actions", []),
        "threads": [t for t in threads if not t.get("resolved") and not t.get("deleted")],
        "resolved": sum(1 for t in threads if t.get("resolved")),
        "html": html.decode("utf-8", "replace") if code == 200 and len(html) <= MAX_BRIDGE_BYTES else None,
        **_editor_view(state.load(), head["id"]),
    }


@router.get("/doc")
async def doc(id: str):
    return await asyncio.to_thread(_doc, _doc_id(id))


@router.post("/act")
async def act(body: dict):
    action = body.get("action")
    if not isinstance(action, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", action):
        raise HTTPException(400, "bad action")
    return await asyncio.to_thread(_cli, ["act", _doc_id(body.get("doc")), action])


def _text(body: dict) -> str:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise HTTPException(400, "empty or too long")
    return text


@router.post("/comment")
async def comment(body: dict):
    return await asyncio.to_thread(_cli, ["thread", "new", _doc_id(body.get("doc")), "--document", "-m", "-"], _text(body))


def _thread(body: dict) -> str:
    t = body.get("thread")
    if not isinstance(t, str) or not THREAD_ID.match(t):
        raise HTTPException(400, "bad thread id")
    return t


@router.post("/reply")
async def reply(body: dict):
    args = ["thread", "reply", _doc_id(body.get("doc")), _thread(body), "-m", "-"]
    if body.get("resolve") is True:
        args.append("--resolve")
    return await asyncio.to_thread(_cli, args, _text(body))


@router.post("/resolve")
async def resolve(body: dict):
    return await asyncio.to_thread(_cli, ["thread", "resolve", _doc_id(body.get("doc")), _thread(body)])


def _set_editor(doc: str, to: str) -> dict:
    from annotary_hermes import docs as docs_mod
    try:
        docs_mod.set_editor_for_handle(doc, to)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return _editor_view(state.load(), doc)


@router.post("/editor")
async def editor(body: dict):
    return await asyncio.to_thread(_set_editor, _doc_id(body.get("doc")), str(body.get("to") or ""))


@router.get("/shell")
async def shell():
    html = await asyncio.to_thread(bridge.shell)
    if html is None:
        raise HTTPException(501, "this Annotary server has no embed mode yet")
    return {"html": html, "protocol": bridge.PROTOCOL}


@router.post("/proxy")
async def proxy(body: dict):
    """One ``annotary-req`` from the frame, answered as the fields of ``annotary-res``."""
    await asyncio.to_thread(_owner)
    return await asyncio.to_thread(bridge.request, body)
