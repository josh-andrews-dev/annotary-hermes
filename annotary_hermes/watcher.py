"""The wake-up watcher, in the gateway: one thread per profile follows Annotary's events.

Each profile's thread acts only on wake-ups for its own profile, because Hermes lets a plugin
inject only into its own profile's sessions. One thread (whichever holds the leader lock) also
broadcasts live updates to Desktop and Webapp windows and runs the 5-minute reconcile.
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import accounts, docs, paths, rules, server, state

log = logging.getLogger("annotary_hermes")
POLL_WAIT = 25  # seconds a long-poll parks (Annotary caps it at 30)

Inject = Callable[[str, str], bool]  # (text, session_key) -> accepted
Broadcast = Callable[[str, dict], None]  # (event name, payload)


#: Hermes's own route for a programmatic message to a profile's Bot: `chat -c TITLE --create-if-missing`
#: runs one turn in that titled chat, creating it if needed (Bot Mode's agent-to-agent DMs use it too).
BOT_CHAT = "Bot Chat"
WAKE_FILE_TTL = 3600


def _hermes_argv() -> list[str]:
    exe = shutil.which("hermes")
    return [exe] if exe else [sys.executable, "-m", "hermes_cli.main"]


_bot_chats: dict[str, subprocess.Popen] = {}  # profile -> its running Bot Chat turn
_bot_chats_lock = threading.Lock()


def wake_bot_chat(profile: str, text: str, root: Path | None = None, *, spawn=subprocess.Popen,
                  on_fail: Callable[[], None] | None = None) -> bool:
    """Run one turn of *profile*'s Bot in its "Bot Chat" with *text*: for a Bot Hermes has no live
    chat of to inject into (it never used Annotary). Callers check the person's consent first.

    One turn per Bot at a time: while one runs, this returns False (the wake stays a notification).
    A turn that exits nonzero calls *on_fail*, so the wake is not lost."""
    folder = paths.app_dir(root) / "wakes"
    with _bot_chats_lock:
        running = _bot_chats.get(profile)
        if running is not None and running.poll() is None:
            return False
        folder.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for old in folder.glob("*.txt"):  # left by a crash; a running turn's file is newer
            try:
                if now - old.stat().st_mtime > WAKE_FILE_TTL:
                    old.unlink()
            except OSError:
                pass
        query = folder / f"{profile}-{secrets.token_hex(6)}.txt"
        query.write_text(text, encoding="utf-8")
        try:
            child = spawn([*_hermes_argv(), "-p", profile, "chat", "--in", str(Path.home()), "-c", BOT_CHAT,
                           "--create-if-missing", "-Q", "--query-file", str(query)],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          start_new_session=True)
        except OSError as e:
            query.unlink(missing_ok=True)
            log.warning("annotary: could not wake %s in its Bot Chat: %s", profile, e)
            return False
        _bot_chats[profile] = child

    def reap() -> None:
        err = b""
        try:
            _, err = child.communicate()
        except Exception:  # noqa: BLE001
            pass
        query.unlink(missing_ok=True)
        with _bot_chats_lock:
            if _bot_chats.get(profile) is child:
                del _bot_chats[profile]
        if child.returncode:
            log.warning("annotary: %s's Bot Chat turn failed (exit %s): %s", profile, child.returncode,
                        (err or b"").decode("utf-8", "replace").strip()[-300:])
            if on_fail:
                on_fail()
    threading.Thread(target=reap, name=f"annotary-botchat-{profile}", daemon=True).start()
    return True


def head_seq(tok: str) -> int:
    return int(server.api(tok, "GET", "/api/v1/events?wait=0&limit=1").get("seq") or 0)


def _thread_digest(tok: str, doc: str, root: Path | None, me: str = "") -> str:
    """Every open Thread with its replies, as the woken agent's reading list. A Thread with no
    reply from *me* is marked: it is waiting for an answer."""
    try:
        rows = docs.read_threads(tok, doc, open_only=True)
    except server.ServerError:
        rows = []
    if not rows:
        return "No open Threads."
    lines = []
    for t in rows[:40]:
        waiting = " (waiting for your answer)" if me and not any(r["author"] == me for r in t["replies"]) else ""
        lines.append(f"- {t['id']} @{t['author']} on {t['where']}{waiting}: "
                     f"{' '.join(str(t['body'] or '').split())[:600]}")
        for r in t["replies"][-10:]:
            lines.append(f"    - {r['id']} @{r['author']}: {' '.join(str(r['body'] or '').split())[:600]}")
    return "Open Threads:\n" + "\n".join(lines)


#: How to answer a Thread, the same in the skill, the tool descriptions and every wake-up.
ANSWER = ("answer each Thread you acted on with annotary_reply, briefly, like a colleague: what changed "
          "and in which Version (\"Done in v3: split the intro\"), or why not (\"Kept: the spec fixes "
          "it\"). A question gets an answer, no edit. Unclear? Ask in that Thread, don't guess. "
          "resolve=true only on a Thread you fully addressed")


def message_for(w: rules.Wake, *, me: str, digest: str) -> str:
    title = f'"{w.name}" ({w.doc})'
    if w.reason == "review":
        label = "Send back" if w.action == "send-back" else "Approve"
        if w.action == "send-back":
            todo = (f"The review is over. Fix what the Threads ask, push one new Version with "
                    f"annotary_push_version (doc={w.doc}), then {ANSWER}.")
        else:
            todo = ("The Document is approved. Do not push. Answer every open Thread that is waiting for "
                    "you (a question gets an answer, an unclear comment a question back), then tell the "
                    "person what happens next.")
        return f"[Annotary] @{w.by} chose {label} on {title}.\n{digest}\n{todo}"
    return (f"[Annotary] @{w.by} mentioned you (@{me}) in Thread {w.thread} on {title}: \"{w.excerpt}\"\n"
            f"Read it with annotary_threads and answer in that Thread with annotary_reply: the answer, or a "
            "question back if it is unclear. Do not push a new Version: you are answering, not editing.")


class Watcher:
    def __init__(self, profile: str, inject: Inject, broadcast: Optional[Broadcast] = None,
                 root: Path | None = None, *, allowed: Callable[[], bool] = lambda: False,
                 bot_chat: Callable[..., bool] = wake_bot_chat):
        self.profile = profile
        self.inject = inject
        self.allowed = allowed  # the person's consent to wake this profile (allow_gateway_injection)
        self.bot_chat = bot_chat
        self.broadcast = broadcast
        self.root = root
        self.stop = threading.Event()
        self._leader_file = None
        self._last_reconcile = 0.0

    # -- leadership: one thread per install broadcasts and reconciles
    def _try_lead(self) -> bool:
        if self._leader_file is not None:
            return True
        import fcntl
        f = open(paths.app_dir(self.root) / "leader.lock", "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return False
        self._leader_file = f
        return True

    def _cursor(self, tok: str) -> int:
        cur = state.load(self.root)["cursors"].get(self.profile)
        if cur is None:
            cur = head_seq(tok)
            self._save_cursor(cur)
        return int(cur)

    def _save_cursor(self, seq: int) -> None:
        def work(st: dict) -> None:
            st["cursors"][self.profile] = seq
        state.update(work, self.root)

    def deliver(self, w: rules.Wake) -> dict:
        """Wake this profile's session for *w*, or leave a notice when waking is off."""
        st = state.load(self.root)
        doc = st["docs"].get(w.doc, {})
        if w.reason == "review" or doc.get("editor") == self.profile:
            key = doc.get("session_key") or st["sessions"].get(self.profile, {}).get("session_key", "")
        else:
            key = st["sessions"].get(self.profile, {}).get("session_key", "")
        if w.by_agent:
            def cap(s: dict) -> bool:
                ok, hist = rules.allow_agent_wake(s["agent_wakes"].get(w.doc, []), time.time())
                s["agent_wakes"][w.doc] = hist
                return ok
            if not state.update(cap, self.root):
                return self._record(w, "capped", key)
        tok = accounts.token_for(self.profile, self.root) or ""
        me = accounts.handle_of(self.profile, self.root) or self.profile
        digest = _thread_digest(tok, w.doc, self.root, me) if w.reason == "review" else ""
        text = message_for(w, me=me, digest=digest)
        ok = False
        try:
            ok = bool(self.inject(text, key))
            # No live chat of this Bot (it never used Annotary, or that chat is gone): its Bot Chat.
            if not ok and self._consented():
                ok = bool(self.bot_chat(self.profile, text, self.root, on_fail=lambda: self._notify(w, me)))
        except Exception as e:  # noqa: BLE001 — a failed wake must not stop the watcher
            log.warning("annotary: wake for %s failed: %s", self.profile, e)
        if not ok:
            self._notify(w, me)
        return self._record(w, "woke" if ok else "notified", key)

    def _consented(self) -> bool:
        try:
            return bool(self.allowed())
        except Exception:  # noqa: BLE001 — unknown consent is no consent
            return False

    def _notify(self, w: rules.Wake, me: str) -> None:
        """Keep *w* for the Bot's next tool call, and tell open windows."""
        def queue(s: dict) -> None:
            s["pending"].setdefault(self.profile, []).append(
                {"reason": w.reason, "doc": w.doc, "name": w.name, "by": w.by, "action": w.action,
                 "thread": w.thread, "excerpt": w.excerpt, "seq": w.seq})
            s["pending"][self.profile] = s["pending"][self.profile][-20:]
        state.update(queue, self.root)
        if self.broadcast:
            self.broadcast("notify", {"doc": w.doc, "name": w.name, "reason": w.reason, "by": w.by,
                                      "action": w.action, "profile": self.profile, "bot": me})

    def _record(self, w: rules.Wake, outcome: str, key: str) -> dict:
        rec = {"at": time.time(), "profile": self.profile, "reason": w.reason, "doc": w.doc, "by": w.by,
               "action": w.action, "thread": w.thread, "seq": w.seq, "outcome": outcome,
               "session": bool(key)}
        def work(s: dict) -> None:
            s.setdefault("wake_log", []).append(rec)
            s["wake_log"] = s["wake_log"][-100:]
        state.update(work, self.root)
        log.info("annotary: %s: %s for %s on %s (seq %s)", rules.OUTCOME_TEXT.get(outcome, outcome), w.reason,
                 self.profile, w.doc, w.seq)
        return rec

    def step(self, wait: int = POLL_WAIT) -> list[dict]:
        """One long-poll: handle what arrived, advance the cursor. Returns the wake records."""
        server.ensure_running(self.root)
        leader = self._try_lead()
        if leader and time.time() - self._last_reconcile >= accounts.GATEWAY_RECONCILE_EVERY:
            self._last_reconcile = time.time()
            try:
                accounts.reconcile(self.root)
            except Exception as e:  # noqa: BLE001
                log.warning("annotary: reconcile failed: %s", e)
        tok = server.owner_token(self.root)
        since = self._cursor(tok)
        page = server.api(tok, "GET", f"/api/v1/events?since={since}&wait={wait}&limit=200",
                          timeout=wait + 15)
        events = page.get("events") or []
        out: list[dict] = []
        if events:
            st = state.load(self.root)
            managed = {v["handle"]: k for k, v in st["members"].items()}
            for ev in events:
                editor = st["docs"].get(ev.get("doc") or "", {}).get("editor")
                for w in rules.decide(ev, managed=managed, editor=editor):
                    if w.profile == self.profile:
                        out.append(self.deliver(w))
            if leader and self.broadcast:
                for doc in sorted({e.get("doc") for e in events if e.get("doc")}):
                    self.broadcast("changed", {"doc": doc, "seq": int(page.get("seq") or 0)})
        self._save_cursor(int(page.get("seq") or since))
        return out

    def run(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            try:
                self.step()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001 — keep watching through restarts
                log.warning("annotary: watcher (%s) error: %s", self.profile, e)
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name=f"annotary-watch-{self.profile}", daemon=True)
        t.start()
        return t
