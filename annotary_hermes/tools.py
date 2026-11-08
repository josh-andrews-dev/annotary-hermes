"""The agent tools, independent of Hermes: each takes the calling profile and session.

They run the bundled CLI (argv only, no shell, the profile's Token in the environment), so
Assets and Sidecars behave as in Annotary. Every result is a JSON-ready dict.
"""

from __future__ import annotations

import functools
import json
import re
import secrets
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import accounts, docs, paths, rules, server, state

CARD = '::annotary{{doc="{doc}"}}'
DOC_RE = re.compile(r"^[A-Za-z0-9._/~ -]{1,200}$")
READ_MAX_CHARS = 200_000  # what one tool result may hand the model


@dataclass
class Caller:
    profile: str
    session_key: str = ""
    surface: str = ""
    cwd: str = ""
    injection_allowed: bool = False


class ToolError(Exception):
    pass


def _prepare(c: Caller, root: Path | None = None) -> str:
    """Server up, Members current, this profile's Token. Also notes the calling session."""
    server.ensure_running(root)
    try:
        accounts.reconcile_if_due(root)
    except server.ServerError:
        pass
    tok = accounts.token_for(c.profile, root)
    if not tok:
        accounts.reconcile(root)
        tok = accounts.token_for(c.profile, root)
    if not tok:
        raise ToolError(f"profile {c.profile} has no Annotary Member; run `hermes annotary doctor`")
    docs.note_session(c.profile, c.session_key, c.surface, root)
    return tok


def _cli_json(tok: str, args: list[str], root: Path | None, **kw):
    r = server.run_cli(tok, [*args, "--json"], root=root, **kw)
    if r.returncode != 0:
        raise ToolError((r.stderr.strip() or r.stdout.strip())[-600:] or f"annotary {args[0]} failed ({r.returncode})")
    out = r.stdout.strip()
    try:
        return json.loads(out) if out else {}
    except ValueError:
        return [json.loads(line) for line in out.splitlines() if line.strip()]


def _check_doc(doc: str) -> str:
    doc = (doc or "").strip()
    if not doc or not DOC_RE.match(doc) or doc.startswith("-"):
        raise ToolError("doc must be a Document id or Name")
    return doc


def _pending(c: Caller, root: Path | None) -> list[dict]:
    """Wake-ups this profile missed while waking was off: shown once, then cleared."""
    def work(st: dict) -> list:
        return st["pending"].pop(c.profile, [])
    return state.update(work, root)


def _with_pending(fn):
    """Every tool's answer carries the wake-ups this profile missed while waking was off, once."""
    @functools.wraps(fn)
    def run(c: Caller, *args, root: Path | None = None, **kwargs):
        out = fn(c, *args, root=root, **kwargs)
        pend = _pending(c, root)
        if pend and isinstance(out, dict):
            out["missed_wakeups"] = pend
        return out
    return run


def links(doc: str) -> dict:
    q = urllib.parse.urlencode({"doc": doc})
    return {"desktop": f"hermes://open/annotary?{q}", "webapp_path": f"#/annotary?{q}"}


def _present(c: Caller, doc_id: str) -> dict:
    out = {"links": links(doc_id)}
    if c.surface == "desktop":
        out["card"] = CARD.format(doc=doc_id)
        out["show_card"] = "Put the card line on a paragraph of its own in your reply; Desktop draws it."
    else:
        out["show_link"] = "Give the person the desktop link; on a phone they open the Annotary page in the Webapp."
    return out


def _wake_hint(c: Caller, root: Path | None) -> str | None:
    """Ask once (D5): the first share tells the person how to let comments wake the chat."""
    if c.injection_allowed:
        return None
    def work(st: dict) -> bool:
        if st["hinted"].get(c.profile):
            return False
        st["hinted"][c.profile] = True
        return True
    if not state.update(work, root):
        return None
    return ("Tell the person: Send back, Approve and @mentions on this Document can wake this chat. "
            "To allow it, run `hermes annotary wake on` (or turn on gateway injection for Annotary in "
            "Settings → Plugins). Until then they show as notifications, and you see them on your next "
            "Annotary tool call.")


def _stem(name: str) -> str:
    """A file stem for *name*. Annotary names a new Document after its file's stem, verbatim, so
    only what a file name cannot hold is replaced."""
    stem = re.sub(r"[/\\\x00-\x1f\x7f]+", "-", " ".join((name or "").split())).strip(" .-")[:80].strip(" .-")
    return stem or "document"


def _write(p: Path, markdown: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown if markdown.endswith("\n") else markdown + "\n", encoding="utf-8")
    return p


def _doc_share_file(c: Caller, doc_id: str, name: str, root: Path | None) -> Path:
    """A Document's own Markdown file: ``shares/<doc id>/<name>.md``, so its Sidecar binds only it."""
    return paths.shares_dir(c.profile, root) / doc_id / f"{_stem(name)}.md"


def _sidecar_doc(file: Path) -> str | None:
    """The Document a file's Sidecar (``<name>.annotary`` beside it) binds it to, if any."""
    try:
        return str(json.loads(file.with_suffix(".annotary").read_text(encoding="utf-8")).get("id") or "") or None
    except (OSError, ValueError, AttributeError):
        return None


def _resolve_path(c: Caller, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(c.cwd or ".") / p
    p = p.resolve()
    if p.suffix.lower() not in (".md", ".markdown"):
        raise ToolError("path must be a Markdown file (.md)")
    if not p.is_file():
        raise ToolError(f"no file at {p}")
    return p


@_with_pending
def share(c: Caller, *, path: str = "", markdown: str = "", name: str = "", message: str = "",
          root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    if bool(path) == bool(markdown):
        raise ToolError("give exactly one of path or markdown")
    staging = None
    if markdown:
        # A fresh folder per share: a Sidecar from an earlier share must never bind this one.
        title = name or (markdown.lstrip("# ").splitlines() or ["document"])[0]
        staging = paths.shares_dir(c.profile, root) / f".new-{secrets.token_hex(6)}"
        file = _write(staging / f"{_stem(title)}.md", markdown)
    else:
        file = _resolve_path(c, path)
        bound = _sidecar_doc(file)
        if bound:
            # The file already belongs to a Document: this is a new Version of it, under the same
            # rules as annotary_push_version (editor only, never mid-review), and its editor stays.
            out = push_version.__wrapped__(c, doc=bound, path=str(file), message=message, root=root)
            if not out.get("refused"):
                out["note"] = f"{file.name} is already the Document {bound}: this pushed a new Version of it."
            return out
    try:
        pushed = _cli_json(tok, ["push", file.name, "-m", message or "shared from Hermes"], root, cwd=file.parent)
    except ToolError:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    doc_id = pushed["id"]
    if staging:
        final = paths.shares_dir(c.profile, root) / doc_id
        if final.exists():
            shutil.rmtree(final)
        staging.rename(final)
        file = final / file.name
    docs.record_share(doc_id, name=pushed.get("name", ""), profile=c.profile, session_key=c.session_key,
                      surface=c.surface, path=str(file), root=root)
    out = {"id": doc_id, "name": pushed.get("name"), "version": pushed.get("version"),
           "editor": f"@{accounts.handle_of(c.profile, root)}", **_present(c, doc_id),
           "next": "Wait for the person's review. Do not push again until they Send back or Approve."}
    hint = _wake_hint(c, root)
    if hint:
        out["tell_the_person"] = hint
    return out


@_with_pending
def threads(c: Caller, *, doc: str, open_only: bool = True, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    head = docs.resolve_id(_check_doc(doc), tok, root)
    rows = docs.read_threads(tok, head["id"], open_only=open_only)
    entry = docs.info(head["id"], root) or {}
    editor = entry.get("editor")
    return {"doc": head, "editor": f"@{accounts.handle_of(editor, root)}" if editor else None,
            "you_are_editor": editor == c.profile, "threads": rows}


def _head_text(tok: str, doc: str, root: Path | None) -> tuple[dict, str]:
    """The head Version's header and its Markdown source, byte for byte."""
    head = docs.resolve_id(doc, tok, root)
    with tempfile.TemporaryDirectory() as out:
        r = server.run_cli(tok, ["pull", head["id"], "--version", str(head["version"]), "--out", out], root=root)
        if r.returncode != 0:
            raise ToolError(r.stderr.strip()[-600:] or f"could not read {doc}")
        return head, next(Path(out).glob("*.md")).read_bytes().decode("utf-8")


def _find_quote(text: str, quote: str) -> tuple[str, str]:
    """The ``L:C-L:C`` anchor of *quote* in *text* (lines from 1, columns from 0 in code points,
    half-open), and "", or "" and why it cannot be anchored."""
    hits, at = [], text.find(quote)
    while at >= 0:
        hits.append(at)
        at = text.find(quote, at + 1)
    if len(hits) > 1:
        return "", (f"That quote appears {len(hits)} times in this Version. Quote a longer passage, "
                    "so it matches exactly one place.")
    if not hits:
        same_words = " ".join(quote.split()).lower() in " ".join(text.split()).lower()
        return "", (("The words are there, but with different spacing or capitals. " if same_words else
                     "That quote is not in this Version. ")
                    + "Copy the passage exactly from annotary_read's text, Markdown included.")

    def where(i: int) -> str:
        return f"{text.count(chr(10), 0, i) + 1}:{i - (text.rfind(chr(10), 0, i) + 1)}"

    return f"{where(hits[0])}-{where(hits[0] + len(quote))}", ""


@_with_pending
def read(c: Caller, *, doc: str, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    head, text = _head_text(tok, _check_doc(doc), root)
    editor = (docs.info(head["id"], root) or {}).get("editor")
    return {"doc": head["id"], "name": head.get("name"), "version": head["version"],
            "editor": f"@{accounts.handle_of(editor, root)}" if editor else None,
            "you_are_editor": editor == c.profile, "text": text[:READ_MAX_CHARS],
            **({"truncated": True} if len(text) > READ_MAX_CHARS else {})}


@_with_pending
def comment(c: Caller, *, doc: str, quote: str, body: str, version: int = 0, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    doc = _check_doc(doc)
    quote = (quote or "").strip()
    if not quote:
        raise ToolError("quote is empty: give the exact passage this comment is about")
    if not (body or "").strip():
        raise ToolError("body is empty")
    head, text = _head_text(tok, doc, root)
    doc_id, head_version = head["id"], head["version"]

    def refused(reason: str) -> dict:
        return {"refused": True, "reason": reason, "doc": doc_id, "version": head_version}

    moved = "Read it again with annotary_read, then comment on what it says now."
    if version and int(version) != head_version:
        return refused(f"You read Version {version}, but this Document is now at Version {head_version}. {moved}")
    anchor, why = _find_quote(text, quote)
    if not anchor:
        return refused(why)
    r = server.run_cli(tok, ["thread", "new", doc_id, anchor, "-m", "-", "--version", str(head_version), "--json"],
                       root=root, stdin=body)
    if r.returncode == 5:  # the CLI's own refusal: head moved after the text above was read
        return refused(f"This Document changed while you were commenting. {moved}")
    if r.returncode != 0:
        raise ToolError(r.stderr.strip()[-600:] or f"annotary thread new failed ({r.returncode})")
    return {**json.loads(r.stdout), "doc": doc_id, "version": head_version}


@_with_pending
def reply(c: Caller, *, doc: str, thread: str, text: str, resolve: bool = False,
          root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    doc = _check_doc(doc)
    if not re.fullmatch(r"t\d+", thread or ""):
        raise ToolError("thread must be a Thread id like t3")
    if not (text or "").strip():
        raise ToolError("text is empty")
    args = ["thread", "reply", doc, thread, "-m", "-", *(["--resolve"] if resolve else [])]
    return _cli_json(tok, args, root, stdin=text)


@_with_pending
def push_version(c: Caller, *, doc: str, path: str = "", markdown: str = "", message: str = "",
                 review_over: bool = False, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    doc = _check_doc(doc)
    head = docs.resolve_id(doc, tok, root)
    doc_id = head["id"]
    entry = docs.info(doc_id, root)
    if entry is None:  # shared outside this plugin: the first agent to push becomes its editor
        entry = docs.set_editor(doc_id, c.profile, session_key=c.session_key, root=root)
    editor = entry.get("editor")
    refusal = rules.push_refusal(
        profile=c.profile, editor=editor, editor_handle=accounts.handle_of(editor, root) if editor else None,
        review_is_open=docs.review_is_open(doc_id, root), review_over=review_over)
    if refusal:
        return {"refused": True, "reason": refusal, "doc": doc_id}
    if bool(path) == bool(markdown):
        if not path and not markdown and entry.get("path"):
            raise ToolError("give path or markdown: the new content of the Document")
        raise ToolError("give exactly one of path or markdown")
    if markdown:
        known = Path(entry["path"]) if entry.get("path") else None
        if not known or _sidecar_doc(known) not in (None, doc_id):
            known = _doc_share_file(c, doc_id, head.get("name") or doc_id, root)
        file = _write(known, markdown)
    else:
        file = _resolve_path(c, path)
    pushed = _cli_json(tok, ["push", file.name, "--doc", doc_id, "-m", message or "update"],
                       root, cwd=file.parent)
    if c.session_key:
        def work(st: dict) -> None:
            st["docs"].setdefault(doc_id, {})["session_key"] = c.session_key
            st["docs"][doc_id]["path"] = str(file)
        state.update(work, root)
    return {**pushed, **_present(c, doc_id),
            "next": _answer_next(pushed.get("version"))}


def _answer_next(version) -> str:
    v = f"v{version}" if version else "this Version"
    return (f"Now answer each Thread you acted on with annotary_reply, briefly: what changed in {v} "
            f"(\"Done in {v}: …\"), or why not. A question gets an answer, an unclear comment a question "
            "back. resolve=true only on a Thread you fully addressed.")


@_with_pending
def handoff(c: Caller, *, doc: str, to: str, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    doc_id = docs.resolve_id(_check_doc(doc), tok, root)["id"]
    target = (to or "").lstrip("@").strip()
    active = accounts.active_handles(root)
    pid = active.get(target) or (target if target in active.values() else None)
    if not pid:
        raise ToolError(f"@{target} is not an active Bot of this Hermes install")
    entry = docs.info(doc_id, root) or {}
    if entry.get("editor") and entry["editor"] != c.profile:
        raise ToolError(f"only the editor (@{accounts.handle_of(entry['editor'], root)}) can hand off this Document")
    docs.set_editor(doc_id, pid, root=root)
    return {"doc": doc_id, "editor": f"@{accounts.handle_of(pid, root)}"}


@_with_pending
def act(c: Caller, *, doc: str, action: str, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    doc = _check_doc(doc)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", action or ""):
        raise ToolError("action must be an Action id such as approve or send-back")
    return _cli_json(tok, ["act", doc, action], root)


@_with_pending
def list_docs(c: Caller, *, root: Path | None = None) -> dict:
    tok = _prepare(c, root)
    rows = _cli_json(tok, ["list"], root)
    st = state.load(root)
    for row in rows if isinstance(rows, list) else []:
        editor = st["docs"].get(row.get("id"), {}).get("editor")
        if editor:
            row["editor"] = "@" + st["members"].get(editor, {}).get("handle", editor)
            row["you_are_editor"] = editor == c.profile
    return {"you": f"@{accounts.handle_of(c.profile, root)}", "documents": rows}
