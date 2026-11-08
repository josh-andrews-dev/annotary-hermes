"""Bots reviewing each other: annotary_read, annotary_comment, and a Bot's Send back.

All against a real `annotary serve` (the `hermes` fixture). coder writes; bencha and default review.
"""

import importlib.util
import json
import sys

import pytest
from conftest import ROOT

from annotary_hermes import accounts, docs, rules, server, state, tools, watcher

PLAN = """# Filament sync plan

We poll the AMS every 30 seconds and write changes to the sheet.

The sync runs as a cron routine, with a **manual** button.

Café spools under 50 g are flagged. Spools over 50 g are not.
Spools over 50 g are not.
"""


def caller(profile):
    return tools.Caller(profile=profile, session_key=f"sess-{profile}", surface="cli", cwd="")


def owner_cli(*args, stdin=None):
    r = server.run_cli(server.owner_token(), [*args], stdin=stdin)
    assert r.returncode == 0, r.stderr
    return r


@pytest.fixture()
def doc(hermes):
    accounts.reconcile()
    return tools.share(caller("coder"), markdown=PLAN, name="Plan", message="first")["id"]


class Inbox:
    def __init__(self):
        self.got = []

    def for_profile(self, profile):
        return lambda text, key: (self.got.append((profile, text, key)), True)[1]


def watching(*profiles):
    inbox = Inbox()
    ws = [watcher.Watcher(p, inbox.for_profile(p)) for p in profiles]
    for w in ws:
        w._cursor(server.owner_token())
    return inbox, ws


def drain(ws):
    return [rec for w in ws for rec in w.step(wait=0)]


def threads(doc_id):
    return docs.read_threads(server.owner_token(), doc_id, open_only=False)


def anchored(doc_id, tid):
    """What the server itself recorded as this Thread's anchored text."""
    return json.loads(owner_cli("thread", "show", doc_id, tid, "--json").stdout)[0]["anchor"]["original"]


# ------------------------------------------------------------------ reading


def test_read_gives_a_reviewer_the_source_and_the_version(doc):
    out = tools.read(caller("bencha"), doc=doc)
    assert out["text"] == PLAN and out["version"] == 1
    assert out["editor"] == "@coder" and out["you_are_editor"] is False
    assert "truncated" not in out


def test_read_says_when_it_cut_a_long_document(doc, monkeypatch):
    monkeypatch.setattr(tools, "READ_MAX_CHARS", 10)
    out = tools.read(caller("bencha"), doc=doc)
    assert out["text"] == PLAN[:10] and out["truncated"] is True


# ------------------------------------------------------------------ anchoring


@pytest.mark.parametrize("quote", ["every 30 seconds", "**manual** button", "Café spools under",
                                   "the sheet.\n\nThe sync runs"])
def test_a_comment_is_anchored_on_the_quoted_text(doc, quote):
    out = tools.comment(caller("bencha"), doc=doc, quote=quote, body="Look at this.")
    assert "refused" not in out, out
    (t,) = threads(doc)
    assert t["body"] == "Look at this." and t["author"] == "bencha"
    original = anchored(doc, t["id"])
    assert original["exact"] == quote and original["version"] == 1


def test_the_anchor_is_the_exact_range():
    text = "ab\ncafé x\n"
    assert tools._find_quote(text, "x") == ("2:5-2:6", "")  # columns count code points, not bytes
    assert tools._find_quote(text, "ab\ncafé") == ("1:0-2:4", "")


def test_a_quote_that_is_not_there_is_refused_and_posts_nothing(doc):
    out = tools.comment(caller("bencha"), doc=doc, quote="nothing like this", body="x")
    assert out["refused"] and "not in this Version" in out["reason"] and "annotary_read" in out["reason"]
    assert threads(doc) == []


def test_a_quote_with_the_wrong_spacing_says_so(doc):
    out = tools.comment(caller("bencha"), doc=doc, quote="WE POLL  the AMS", body="x")
    assert out["refused"] and "different spacing or capitals" in out["reason"]


def test_an_ambiguous_quote_is_refused_with_the_count(doc):
    out = tools.comment(caller("bencha"), doc=doc, quote="Spools over 50 g are not.", body="x")
    assert out["refused"] and "2 times" in out["reason"] and "longer" in out["reason"]
    assert threads(doc) == []


@pytest.mark.parametrize("field", ["quote", "body"])
def test_an_empty_quote_or_body_is_an_error(doc, field):
    args = {"quote": "We poll", "body": "x", field: "   "}
    with pytest.raises(tools.ToolError, match=f"{field} is empty"):
        tools.comment(caller("bencha"), doc=doc, **args)
    assert threads(doc) == []


# ------------------------------------------------------------------ a stale view


def test_a_comment_on_a_version_that_moved_on_is_refused(doc):
    tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "\nMore.\n", message="v2")
    out = tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="x", version=1)
    assert out["refused"] and "Version 1" in out["reason"] and "Version 2" in out["reason"]
    assert threads(doc) == []


def test_the_clis_own_version_check_is_a_refusal_too(doc, monkeypatch):
    real = tools._head_text
    monkeypatch.setattr(tools, "_head_text", lambda tok, d, root: (lambda h, t: ({**h, "version": 9}, t))(*real(tok, d, root)))
    out = tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="x")
    assert out["refused"] and "changed while" in out["reason"]
    assert threads(doc) == []


# ------------------------------------------------------------------ who may comment


def test_any_active_member_may_comment_during_an_open_review_and_the_editor_too(doc):
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="I am reviewing this.")
    assert docs.review_is_open(doc)
    for profile in ("bencha", "default", "coder"):
        out = tools.comment(caller(profile), doc=doc, quote="every 30 seconds", body=f"From {profile}.")
        assert "refused" not in out, out


def test_a_reviewer_still_cannot_push(doc):
    out = tools.push_version(caller("bencha"), doc=doc, markdown="# mine\n")
    assert out["refused"] and "annotary_comment" in out["reason"]


# ------------------------------------------------------------------ wake rules


def test_a_plain_comment_wakes_nobody(doc):
    inbox, ws = watching("coder", "bencha", "default")
    tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="No mention here.")
    drain(ws)
    assert inbox.got == []


def test_a_mention_wakes_only_the_named_bot(doc):
    inbox, ws = watching("coder", "bencha", "default")
    tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="@coder why 30 seconds?")
    drain(ws)
    assert [g[0] for g in inbox.got] == ["coder"] and "Do not push" in inbox.got[0][1]


def test_a_bot_is_never_woken_by_its_own_comment(doc):
    inbox, ws = watching("coder", "bencha")
    tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="@bencha note to self")
    drain(ws)
    assert inbox.got == []


def test_the_cap_stops_the_fourth_wake_between_bots(doc):
    inbox, ws = watching("coder")
    for i in range(4):
        tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body=f"@coder question {i}")
    recs = drain(ws)
    assert [r["outcome"] for r in recs] == ["woke", "woke", "woke", "capped"]
    assert len(inbox.got) == 3


# ------------------------------------------------------------------ a Bot's Send back


def test_a_bot_that_is_not_the_editor_can_send_back_and_it_wakes_the_editor(doc):
    inbox, ws = watching("coder", "bencha", "default")
    out = tools.act(caller("default"), doc=doc, action="send-back")
    assert out["action"] == "send-back" and out["by"] == "hermes"
    drain(ws)
    assert [g[0] for g in inbox.got] == ["coder"]
    assert inbox.got[0][2] == "sess-coder"  # the chat that shared it
    assert "chose Send back" in inbox.got[0][1] and "push one new Version" in inbox.got[0][1]


def test_a_bots_approve_wakes_the_editor_and_says_not_to_push(doc):
    inbox, ws = watching("coder")
    tools.act(caller("bencha"), doc=doc, action="approve")
    drain(ws)
    assert "Do not push" in inbox.got[0][1]


def test_the_editors_own_action_wakes_nobody(doc):
    inbox, ws = watching("coder")
    tools.act(caller("coder"), doc=doc, action="send-back")
    drain(ws)
    assert inbox.got == []


def test_a_persons_send_back_still_wakes_the_editor(doc):
    inbox, ws = watching("coder")
    owner_cli("act", doc, "send-back")
    drain(ws)
    assert [g[0] for g in inbox.got] == ["coder"]


def test_the_demo_sequence_fits_under_the_cap(doc):
    inbox, ws = watching("coder", "bencha", "default")
    for quote in ("every 30 seconds", "cron routine", "under 50 g"):
        tools.comment(caller("bencha"), doc=doc, quote=quote, body="Please fix this.")
    tools.act(caller("default"), doc=doc, action="send-back")
    recs = drain(ws)
    assert [(r["profile"], r["reason"], r["outcome"]) for r in recs] == [("coder", "review", "woke")]
    assert len(threads(doc)) == 3
    assert state.load()["agent_wakes"][doc]  # the Send back is the one wake counted


def test_three_mentions_first_would_use_up_the_cap_and_lose_the_send_back(doc):
    inbox, ws = watching("coder")
    for quote in ("every 30 seconds", "cron routine", "under 50 g"):
        tools.comment(caller("bencha"), doc=doc, quote=quote, body="@coder please fix this.")
    tools.act(caller("default"), doc=doc, action="send-back")
    recs = drain(ws)
    assert [r["outcome"] for r in recs] == ["woke", "woke", "woke", "capped"]
    assert recs[-1]["reason"] == "review"


def test_after_a_bots_send_back_the_editor_can_push_when_only_bots_commented(doc):
    tools.comment(caller("bencha"), doc=doc, quote="every 30 seconds", body="Too often.")
    tools.act(caller("default"), doc=doc, action="send-back")
    out = tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "\nv2\n", message="v2")
    assert out["version"] == 2


def test_a_bots_send_back_does_not_end_a_persons_review(doc):
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Still reading this.")
    inbox, ws = watching("coder")
    tools.act(caller("default"), doc=doc, action="send-back")
    drain(ws)
    assert [g[0] for g in inbox.got] == ["coder"]  # the editor hears about it,
    assert docs.review_is_open(doc)  # but the person has not finished
    out = tools.push_version(caller("coder"), doc=doc, markdown="# x\n")
    assert out["refused"] and "A review is open" in out["reason"]


# ------------------------------------------------------------------ the rule, on its own


MANAGED = {"coder": "coder", "scout": "scout"}


def action_event(by, action="send-back"):
    return {"type": "action.taken", "by": by, "doc": "d", "name": "n", "seq": 1, "payload": {"action": action}}


@pytest.mark.parametrize("by, wakes, by_agent", [("owner", True, False), ("scout", True, True), ("coder", False, False)])
def test_a_review_action_wakes_the_editor_unless_the_editor_took_it(by, wakes, by_agent):
    out = rules.decide(action_event(by), managed=MANAGED, editor="coder")
    assert bool(out) == wakes
    if wakes:
        assert out[0].profile == "coder" and out[0].by_agent == by_agent


def test_another_action_wakes_nobody():
    assert rules.decide(action_event("scout", "archive"), managed=MANAGED, editor="coder") == []


def test_a_document_with_no_editor_wakes_nobody():
    assert rules.decide(action_event("scout"), managed=MANAGED, editor=None) == []


# ------------------------------------------------------------------ registration and the skill


class FakeCtx:
    profile_name = "coder"

    def __init__(self):
        self.tools = {}

    def register_tool(self, **kw):
        self.tools[kw["name"]] = kw

    def register_skill(self, *a, **kw):
        pass

    def register_cli_command(self, **kw):
        pass


def registered():
    spec = importlib.util.spec_from_file_location("annotary_comment_plugin_under_test", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin
    spec.loader.exec_module(plugin)
    ctx = FakeCtx()
    plugin.register(ctx)
    return ctx.tools


def test_the_tools_are_registered_like_the_others():
    got = registered()
    for name in ("annotary_comment", "annotary_read"):
        assert got[name]["toolset"] == got["annotary_reply"]["toolset"]
    params = got["annotary_comment"]["schema"]["parameters"]
    assert set(params["required"]) == {"doc", "quote", "body"} and "version" in params["properties"]
    description = got["annotary_comment"]["schema"]["description"]
    for rule in ("does not edit", "wakes nobody", "@mention"):
        assert rule in description


def test_the_skill_tells_a_reviewer_it_comments_and_does_not_edit():
    text = (ROOT / "skills" / "annotary" / "SKILL.md").read_text()
    assert "You comment, you do not edit" in text
    for tool in ("annotary_read", "annotary_comment", "annotary_act"):
        assert tool in text
    assert len(text.encode()) < 24_000
