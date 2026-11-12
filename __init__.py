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
from typing import Callable

from .annotary_hermes import paths, skillmeta, tools
from .annotary_hermes.docs import DESKTOP, GATEWAY
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
    "annotary_read": {
        "description": "Read a Document's current text and Version, to review it or to quote it in annotary_comment.",
        "parameters": {"type": "object", "properties": {"doc": _DOC}, "required": ["doc"]}},
    "annotary_comment": {
        "description": ("Leave a new comment on an exact passage of a Document, as its reviewer. Works during a "
                        "review, and for any Bot, editor or not. A reviewer comments and does not edit: never "
                        "annotary_push_version on a Document you do not edit. A plain comment wakes nobody; "
                        "@mention a Bot in the body to ask it something. Use annotary_reply to answer an "
                        "existing Thread."),
        "parameters": {"type": "object", "properties": {
            "doc": _DOC,
            "quote": {"type": "string", "description": ("The passage, copied exactly from annotary_read's text, "
                                                        "long enough to match one place only")},
            "body": {"type": "string", "description": "The comment (Markdown)"},
            "version": {"type": "integer", "description": ("The Version you read, from annotary_read: "
                                                           "the comment is refused if the Document has moved on")}},
            "required": ["doc", "quote", "body"]}},
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
        "description": ("Take an Action on a Document's head Version (e.g. approve, send-back). Any Bot reviewing a "
                        "Document may send it back; that wakes its editor to fix it. Comment first, so the editor "
                        "knows what to fix. The editor cannot Send back or Approve its own Document."),
        "parameters": {"type": "object", "properties": {
            "doc": _DOC, "action": {"type": "string"}}, "required": ["doc", "action"]}},
    "annotary_list": {
        "description": "List Annotary Documents, who edits each, the person's handle, and wake-ups you missed.",
        "parameters": {"type": "object", "properties": {}, "required": []}},
    "annotary_set_name": {
        "description": ("Set the name Annotary shows for the person, as they told you in chat (\"Rowan\"). While they "
                        "have no name yet, this also gives them a handle made from it (@rowan)."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "The person's name, as they gave it"}}, "required": ["name"]}},
}


def _host_process(argv: list[str] | None = None) -> str:
    """The Hermes host this process may be: the gateway (`gateway run`, or `gateway restart` with no
    service, which Desktop's Restart gateway leaves running the gateway itself), a Desktop backend
    (`dashboard` or `serve`, which host a remote Hermes's Desktop chats), or "" (any other command)."""
    args = list(sys.argv[1:] if argv is None else argv)
    words, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "--profile"):  # the profile's name is not the command
            i += 2
            continue
        if not a.startswith("-"):
            words.append(a)
        i += 1
    if words[:1] == ["gateway"]:
        return GATEWAY if words[1:2] in (["run"], ["restart"]) else ""
    if words[:1] in (["dashboard"], ["serve"]):
        lifecycle = {"--stop", "--status"} & set(args) or words[1:2] == ["register"]
        return "" if lifecycle else DESKTOP
    return ""


def _host_ready(ctx, host: str) -> Callable[[], bool]:
    """Whether this process's Hermes host is live and takes injected messages (a `gateway restart`
    client that hands off to a service never is). A Hermes without these flags: always ready."""
    attr = "has_gateway_message_injector" if host == GATEWAY else "has_tui_message_injector"
    manager = getattr(ctx, "_manager", None)
    if manager is None or not hasattr(type(manager), attr):
        return lambda: True
    return lambda: bool(getattr(manager, attr))


def _session_key(kwargs: dict) -> str:
    try:
        from gateway.session_context import get_session_env
        key = get_session_env("HERMES_SESSION_KEY", "")
    except ImportError:
        key = ""
    return key or str(kwargs.get("session_id") or "")


def register(ctx):
    host = _host_process()

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
        if host == DESKTOP and not surface:
            surface = "desktop"  # the Desktop backend's chats (Desktop or the Webapp) set no platform
        return tools.Caller(profile=ctx.profile_name, session_key=_session_key(kwargs), surface=surface,
                            cwd=cwd, injection_allowed=allowed, host=host or GATEWAY)

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
        "annotary_read": (tools.read, pick("doc")),
        "annotary_comment": (tools.comment, pick("doc", "quote", "body", "version")),
        "annotary_threads": (tools.threads, pick("doc", "open_only")),
        "annotary_reply": (tools.reply, pick("doc", "thread", "text", "resolve")),
        "annotary_push_version": (tools.push_version, pick("doc", "path", "markdown", "message", "review_over")),
        "annotary_handoff": (tools.handoff, pick("doc", "to")),
        "annotary_act": (tools.act, pick("doc", "action")),
        "annotary_list": (tools.list_docs, pick()),
        "annotary_set_name": (tools.set_name, pick("name")),
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

    if host:
        _start_watcher(ctx, host)


def _start_watcher(ctx, host: str) -> None:
    from .annotary_hermes import watcher

    profile = ctx.profile_name  # captured here: a thread started from register() sees `default`

    def allowed() -> bool:  # the person's consent for this profile, read from its own config
        return annotary_cli.wake_allowed(profile)

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

    w = watcher.Watcher(profile, inject, broadcast, allowed=allowed, host=host, ready=_host_ready(ctx, host))
    w.start()
    try:
        ctx.on_unload(w.stop.set)
    except Exception:  # noqa: BLE001
        pass
