"""The wake and editor rules (D5, D11), as pure functions."""

from conftest import ROOT

from annotary_hermes import rules

MANAGED = {"coder": "coder", "bencha": "bencha", "hermes": "default"}


def ev(type_, by, *, mentions=(), action=None, seq=1, thread="t1"):
    payload = {"thread": thread} if type_.startswith("thread") else {}
    if action:
        payload["action"] = action
    return {"seq": seq, "type": type_, "by": by, "doc": "d1", "name": "plan", "payload": payload,
            "mentions": list(mentions), "excerpt": "hi"}


def test_plain_comment_wakes_nobody():
    assert rules.decide(ev("thread.created", "josh"), managed=MANAGED, editor="coder") == []
    assert rules.decide(ev("thread.replied", "josh"), managed=MANAGED, editor="coder") == []


def test_send_back_and_approve_wake_the_editor_only():
    for action in ("send-back", "approve"):
        wakes = rules.decide(ev("action.taken", "josh", action=action), managed=MANAGED, editor="coder")
        assert [(w.profile, w.reason, w.action) for w in wakes] == [("coder", "review", action)]


def test_no_editor_no_wake_and_other_actions_ignored():
    assert rules.decide(ev("action.taken", "josh", action="send-back"), managed=MANAGED, editor=None) == []
    assert rules.decide(ev("action.taken", "josh", action="custom"), managed=MANAGED, editor="coder") == []


def test_an_agents_own_action_wakes_nobody():
    assert rules.decide(ev("action.taken", "coder", action="approve"), managed=MANAGED, editor="coder") == []


def test_mention_wakes_only_the_named_bot():
    wakes = rules.decide(ev("thread.created", "josh", mentions=["bencha", "josh"]), managed=MANAGED, editor="coder")
    assert [(w.profile, w.reason, w.by_agent) for w in wakes] == [("bencha", "mention", False)]


def test_never_for_an_agents_own_comment():
    assert rules.decide(ev("thread.replied", "coder", mentions=["coder"]), managed=MANAGED, editor="coder") == []


def test_agent_mention_of_agent_is_marked():
    wakes = rules.decide(ev("thread.created", "coder", mentions=["bencha"]), managed=MANAGED, editor="coder")
    assert [(w.profile, w.by_agent) for w in wakes] == [("bencha", True)]


def test_a_bots_reply_naming_another_bot_wakes_nobody():
    """Two Bots acknowledging each other ("agreed with @coder") woke each other until the cap."""
    assert rules.decide(ev("thread.replied", "coder", mentions=["bencha"]), managed=MANAGED, editor="coder") == []
    person = rules.decide(ev("thread.replied", "josh", mentions=["bencha"]), managed=MANAGED, editor="coder")
    assert [(w.profile, w.by_agent) for w in person] == [("bencha", False)]  # the person's reply still does


def test_a_mention_wake_says_not_to_resolve_the_askers_thread():
    from annotary_hermes import watcher
    w = rules.Wake(profile="bencha", reason="mention", doc="d1", name="Plan", by="josh", thread="t1", excerpt="hi")
    assert "Do not resolve the Thread" in watcher.message_for(w, me="bencha", digest="")


def test_agent_to_agent_cap_is_three_per_hour():
    hist, now, allowed = [], 1000.0, []
    for i in range(5):
        ok, hist = rules.allow_agent_wake(hist, now + i)
        allowed.append(ok)
    assert allowed == [True, True, True, False, False]
    ok, _ = rules.allow_agent_wake(hist, now + rules.HOUR + 10)
    assert ok


def test_review_open_until_send_back_or_approve():
    push = ev("version.pushed", "coder")
    comment = ev("thread.created", "josh")
    assert rules.review_open([push], managed=MANAGED) is False
    assert rules.review_open([push, comment], managed=MANAGED) is True
    assert rules.review_open([push, comment, ev("action.taken", "josh", action="send-back")], managed=MANAGED) is False
    # an agent's comment is not a review, and a new push starts over
    assert rules.review_open([push, ev("thread.replied", "coder")], managed=MANAGED) is False
    assert rules.review_open([push, comment, ev("action.taken", "josh", action="send-back"), push], managed=MANAGED) is False


def test_push_refusal():
    assert rules.push_refusal(profile="bencha", editor="coder", editor_handle="coder", review_is_open=False,
                              review_over=False).startswith("@coder edits this Document")
    assert "review is open" in rules.push_refusal(profile="coder", editor="coder", editor_handle="coder",
                                                  review_is_open=True, review_over=False)
    assert rules.push_refusal(profile="coder", editor="coder", editor_handle="coder", review_is_open=True,
                              review_over=True) is None
    assert rules.push_refusal(profile="coder", editor="coder", editor_handle="coder", review_is_open=False,
                              review_over=False) is None


def test_review_restarts_at_the_latest_push_or_review_action():
    push = ev("version.pushed", "coder")
    comment = ev("thread.created", "josh")
    send_back = ev("action.taken", "josh", action="send-back")
    approve = ev("action.taken", "josh", action="approve")
    assert rules.review_open([push, comment, send_back], managed=MANAGED) is False
    assert rules.review_open([push, comment], managed=MANAGED) is True
    assert rules.review_open([push, approve, ev("thread.replied", "coder")], managed=MANAGED) is False
    # after Approve, a new comment from the person opens a new review on the same Version
    assert rules.review_open([push, comment, approve, comment], managed=MANAGED) is True
    assert rules.review_open([push, comment, send_back, comment], managed=MANAGED) is True
    # an agent's own Approve does not end the person's review
    assert rules.review_open([push, comment, ev("action.taken", "bencha", action="approve")], managed=MANAGED) is True


def test_the_rule_summary_says_what_the_readme_says_about_approve():
    summary, readme = (" ".join(t.split()) for t in (rules.__doc__, (ROOT / "README.md").read_text()))
    wording = "After Send back it fixes what you asked, pushes one new Version and answers each Thread; " \
              "after Approve it answers what's waiting and does not push."
    assert wording in readme and wording in summary


# ------------------------------------------------------------------ Questions and Markup (annotary v0.8.0)


def answered(by, key="D1", option="A"):
    return {"seq": 9, "type": "question.answered", "by": by, "doc": "d1", "name": "plan",
            "payload": {"key": key, "option": option, "version": 1}, "mentions": [], "excerpt": ""}


def test_an_answer_never_wakes_a_bot():
    """D5 as written: an Answer is read after Send back or Approve, never on its own."""
    for by in ("josh", "bencha", "coder"):
        assert rules.decide(answered(by), managed=MANAGED, editor="coder") == []


def test_an_answer_is_not_a_comment_so_it_opens_no_review_and_blocks_no_push():
    push = ev("version.pushed", "coder")
    assert "question.answered" not in rules.COMMENT_TYPES
    assert rules.review_open([push, answered("josh")], managed=MANAGED) is False
    assert rules.review_open([push, answered("josh"), answered("josh", option="B")], managed=MANAGED) is False
    # a real comment still opens one, with or without Answers around it
    assert rules.review_open([push, answered("josh"), ev("thread.created", "josh")], managed=MANAGED) is True


def test_a_markup_is_a_comment_like_any_other():
    """A Markup arrives as thread.created / thread.replied with markup: true: a plain comment."""
    drawing = ev("thread.created", "josh")
    drawing["payload"]["markup"] = True
    assert rules.decide(drawing, managed=MANAGED, editor="coder") == []
    assert rules.review_open([ev("version.pushed", "coder"), drawing], managed=MANAGED) is True
