"""Annotary for Hermes Agent: the agent half.

register() runs in every `hermes` command, not only in the gateway, so it only registers: tools,
the skill and `hermes annotary`. Nothing starts here except, in the gateway process alone, the
wake-up watcher for this profile. The server starts lazily, from the first tool call, backend
route or `hermes annotary` command.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from .annotary_hermes import paths, skillmeta, tools
from .annotary_hermes import cli as annotary_cli

log = logging.getLogger("annotary_hermes")
TOOLSET = "annotary"

_DOC = {"type": "string", "description": "Document id (e.g. k7q2m9xd) or its unique Name"}
SCHEMAS = {
    "annotary_share": {
        "description": (
            "Share a Markdown document (a plan, spec, design, report) with the person for review in "
            "Annotary, where they comment on exact lines from Desktop, the Webapp or their phone. Use it "
            "whenever you wrote Markdown the person should read and decide on. You become the "
            "Document's editor. Give exactly one of path or markdown."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "A .md file, absolute or relative to the session's folder"},
            "markdown": {"type": "string", "description": "The Markdown text, when there is no file"},
            "name": {"type": "string", "description": "A short name for a new Document from markdown"},
            "message": {"type": "string", "description": "A one-line Version message"}},
            "required": []}},
    "annotary_threads": {
        "description": ("Read a Document's review Threads (comments anchored to lines) with their replies, open "
                        "ones by default. Answer each one you act on with annotary_reply."),
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "open_only": {"type": "boolean", "description": "Only open Threads (default true)"}},
            "required": ["doc"]}},
    "annotary_reply": {
        "description": (
            "Answer one review Thread, briefly, like a colleague: after a push, what changed and in which "
            "Version (\"Done in v3: split the intro\") or why not (\"Kept: the spec fixes it\"); the answer "
            "to a question, with no edit; or a question back when the comment is unclear. resolve=true "
            "only when the Thread is fully addressed."),
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "thread": {"type": "string", "description": "Thread id, e.g. t3"},
            "text": {"type": "string", "description": "Your reply (Markdown); name the Version a change is in (\"Done in v3: …\")"},
            "resolve": {"type": "boolean"}}, "required": ["doc", "thread", "text"]}},
    "annotary_push_version": {
        "description": (
            "Push a new Version of a Document you edit, after the person sent it back. Refused if you "
            "are not its editor, or while a review is open (the person commented and has not sent it "
            "back or approved). Give the full new content as path or markdown. Push once, then answer "
            "each Thread you acted on with annotary_reply, naming this Version."),
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "path": {"type": "string"}, "markdown": {"type": "string"},
            "message": {"type": "string", "description": "What changed, in one line"},
            "review_over": {"type": "boolean", "description": "Only when the person said in chat that the review is over"}},
            "required": ["doc"]}},
    "annotary_handoff": {
        "description": "Make another Bot the Document's editor (only the current editor can).",
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "to": {"type": "string", "description": "The Bot's handle, e.g. @coder"}},
            "required": ["doc", "to"]}},
    "annotary_act": {
        "description": "Take an Action on a Document's head Version (e.g. approve, send-back).",
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "action": {"type": "string"}}, "required": ["doc", "action"]}},
    "annotary_list": {
        "description": "List Annotary Documents, who edits each, and wake-ups you missed.",
        "parameters": {"type": "object", "properties": {}, "required": []}},
}


def _in_gateway() -> bool:
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    return "gateway" in argv and argv[argv.index("gateway") + 1: argv.index("gateway") + 2] == ["run"]


def _session_key(kwargs: dict) -> str:
    try:
        from gateway.session_context import get_session_env
        key = get_session_env("HERMES_SESSION_KEY", "")
    except ImportError:
        key = ""
    return key or str(kwargs.get("session_id") or "")


def register(ctx):
    def caller(kwargs: dict) -> tools.Caller:
        try:
            surface = ctx.session_surface()
        except Exception:  # noqa: BLE001
            surface = ""
        try:
            cwd = ctx.session_cwd()
        except Exception:  # noqa: BLE001
            cwd = ""
        try:  # the consent switch Hermes checks before inject_message (read-only here)
            from hermes_cli.config import load_config_readonly
            entry = (((load_config_readonly() or {}).get("plugins") or {}).get("entries") or {}).get(paths.PLUGIN_ID) or {}
            allowed = entry.get("allow_gateway_injection") is True
        except Exception:  # noqa: BLE001
            allowed = False
        return tools.Caller(profile=ctx.profile_name, session_key=_session_key(kwargs), surface=surface,
                            cwd=cwd, injection_allowed=allowed)

    def handler(fn, params_of):
        def run(args, **kwargs):
            try:
                return json.dumps(fn(caller(kwargs), **params_of(args or {})), default=str)
            except tools.ToolError as e:
                return json.dumps({"error": str(e)})
            except Exception as e:  # noqa: BLE001 — a tool returns its error, never raises
                log.warning("annotary tool failed: %s", e)
                return json.dumps({"error": f"{type(e).__name__}: {e}"})
        return run

    pick = lambda *keys: (lambda a: {k: a[k] for k in keys if k in a and a[k] is not None})  # noqa: E731
    table = {
        "annotary_share": (tools.share, pick("path", "markdown", "name", "message")),
        "annotary_threads": (tools.threads, pick("doc", "open_only")),
        "annotary_reply": (tools.reply, pick("doc", "thread", "text", "resolve")),
        "annotary_push_version": (tools.push_version, pick("doc", "path", "markdown", "message", "review_over")),
        "annotary_handoff": (tools.handoff, pick("doc", "to")),
        "annotary_act": (tools.act, pick("doc", "action")),
        "annotary_list": (tools.list_docs, pick()),
    }
    for name, (fn, params) in table.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema={"name": name, **SCHEMAS[name]},
                          handler=handler(fn, params), emoji="📝")

    skill = Path(__file__).resolve().parent / "skills" / "annotary" / "SKILL.md"
    if skill.is_file():
        meta = skillmeta.frontmatter(skill)
        ctx.register_skill("annotary", skill, description=str(meta.get("description") or ""), frontmatter=meta)

    ctx.register_cli_command(name="annotary", help="Annotary: the private review server, Members and wake-ups",
                             setup_fn=annotary_cli.setup_argparse, handler_fn=annotary_cli.main)

    if _in_gateway():
        _start_watcher(ctx)


def _start_watcher(ctx) -> None:
    from .annotary_hermes import watcher

    profile = ctx.profile_name  # captured here: a thread started from register() sees `default`

    def inject(text: str, session_key: str) -> bool:
        if session_key:
            return bool(ctx.inject_message(text, session_key=session_key))
        return bool(ctx.inject_message(text))

    def broadcast(name: str, payload: dict) -> None:
        if name == "notify" and ctx.get_config("notify_when_off", True) is False:
            return
        try:
            from hermes_cli.plugin_events import broadcast_plugin_event
            broadcast_plugin_event(paths.PLUGIN_ID, name, payload)
        except Exception as e:  # noqa: BLE001
            log.debug("annotary: broadcast failed: %s", e)

    w = watcher.Watcher(profile, inject, broadcast)
    w.start()
    try:
        ctx.on_unload(w.stop.set)
    except Exception:  # noqa: BLE001
        pass
