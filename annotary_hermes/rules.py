"""Annotary's review rule, enforced by the plugin (D5, D11). Pure functions: no I/O.

- A plain Comment wakes nobody.
- Send back or Approve wakes the Document's editor, whether a person or another Bot chose it. Never
  for the editor's own Action. After Send back it fixes what you asked, pushes one new Version and
  answers each Thread; after Approve it answers what's waiting and does not push.
- The editor does not Send back or Approve its own Document: annotary_act refuses it.
- An @mention wakes only the Bot it names, to answer that Thread, never to push. A Bot's reply
  wakes no Bot; a Bot's new comment can.
- Never for an agent's own Comment; a wake from one agent to another (an @mention or a Send back)
  happens at most AGENT_WAKES_PER_HOUR times per Document per hour.
- A push is refused while a review is open: a person has commented on the head Version since it
  was pushed and has neither sent it back nor approved it. A Bot's Action does not end it.
- Only the editor may push.
"""

from __future__ import annotations

from dataclasses import dataclass

REVIEW_ACTIONS = ("send-back", "approve")
AGENT_WAKES_PER_HOUR = 3
# What each wake_log outcome means. "woke" only says Hermes accepted the message, not that a turn ran.
OUTCOME_TEXT = {"woke": "Message handed to Hermes; this does not show a turn ran",
                "notified": "No session took it; kept as a notification",
                "capped": "Dropped: too many wake-ups between Bots on this Document"}
HOUR = 3600.0
COMMENT_TYPES = ("thread.created", "thread.replied")


@dataclass(frozen=True)
class Wake:
    profile: str
    reason: str  # "review" | "mention"
    doc: str
    name: str
    by: str
    action: str = ""
    thread: str = ""
    excerpt: str = ""
    seq: int = 0
    by_agent: bool = False


def decide(event: dict, *, managed: dict[str, str], editor: str | None) -> list[Wake]:
    """The wake-ups one Annotary event calls for, before the agent-to-agent cap.

    *managed* maps each managed agent handle to its profile; *editor* is the Document's editor
    profile, if the plugin knows one."""
    by = event.get("by") or ""
    author = managed.get(by)  # None: a person (the owner or anyone not managed here)
    etype = event.get("type") or ""
    payload = event.get("payload") or {}
    common = dict(doc=event.get("doc") or "", name=event.get("name") or "", by=by, seq=int(event.get("seq") or 0),
                  by_agent=author is not None)
    if etype == "action.taken":
        action = payload.get("action") or ""
        if action in REVIEW_ACTIONS and editor and author != editor:
            return [Wake(profile=editor, reason="review", action=action, **common)]
        return []
    if etype in COMMENT_TYPES:
        # A Bot's reply wakes no other Bot: naming one in passing ("agreed with @hermes") set two
        # Bots answering each other until the cap. A Bot asks another with a new comment instead.
        if author is not None and etype == "thread.replied":
            return []
        out = []
        for handle in event.get("mentions") or []:
            target = managed.get(handle)
            if target is None or target == author:
                continue
            out.append(Wake(profile=target, reason="mention", thread=payload.get("thread") or "",
                            excerpt=event.get("excerpt") or "", **common))
        return out
    return []


def allow_agent_wake(history: list[float], now: float) -> tuple[bool, list[float]]:
    """The cap on agent-to-agent wakes for one Document: (allowed, history to keep)."""
    recent = [t for t in history if now - t < HOUR]
    if len(recent) >= AGENT_WAKES_PER_HOUR:
        return False, recent
    return True, recent + [now]


def review_open(events: list[dict], *, managed: dict[str, str]) -> bool:
    """Whether a review is open, from a Document's events (oldest first): a person has commented
    since the latest push, Send back or Approve (whichever came last), and nothing ended it since."""
    def is_boundary(e: dict) -> bool:
        if e.get("type") == "version.pushed":
            return True
        return (e.get("type") == "action.taken" and (e.get("by") or "") not in managed
                and (e.get("payload") or {}).get("action") in REVIEW_ACTIONS)
    last = max((i for i, e in enumerate(events) if is_boundary(e)), default=-1)
    return any(e.get("type") in COMMENT_TYPES and (e.get("by") or "") not in managed for e in events[last + 1:])


def review_refusal(*, profile: str, editor: str | None) -> str | None:
    """Why *profile* may not Send back or Approve this Document, else None."""
    if editor and editor == profile:
        return ("You are this Document's editor, and an author does not Send back or Approve its own work. "
                "That is for a reviewer: another Bot through annotary_act, or the person in Annotary. "
                "To have another Bot edit it instead, use annotary_handoff.")
    return None


def push_refusal(*, profile: str, editor: str | None, editor_handle: str | None, review_is_open: bool,
                 review_over: bool) -> str | None:
    """Why *profile* may not push a new Version now, else None."""
    if editor and editor != profile:
        who = f"@{editor_handle}" if editor_handle else editor
        return (f"{who} edits this Document: comment on a passage with annotary_comment, or @mention {who} "
                "in a new comment (a Bot's reply wakes no one). Only the editor pushes; the editor can hand off with annotary_handoff.")
    if review_is_open and not review_over:
        return ("A review is open: the person has commented on this Version and has not sent it back "
                "or approved it yet. Do not push. Wait for Send back or Approve (you will be woken), "
                "or push with review_over=true only if the person said in chat that the review is over.")
    return None
