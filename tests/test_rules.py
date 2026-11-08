"""The wake and editor rules (D5, D11), as pure functions."""

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
    assert rules.decide(ev("action.taken", "bencha", action="approve"), managed=MANAGED, editor="coder") == []


def test_mention_wakes_only_the_named_bot():
    wakes = rules.decide(ev("thread.created", "josh", mentions=["bencha", "josh"]), managed=MANAGED, editor="coder")
    assert [(w.profile, w.reason, w.by_agent) for w in wakes] == [("bencha", "mention", False)]


def test_never_for_an_agents_own_comment():
    assert rules.decide(ev("thread.replied", "coder", mentions=["coder"]), managed=MANAGED, editor="coder") == []


def test_agent_mention_of_agent_is_marked():
    wakes = rules.decide(ev("thread.replied", "coder", mentions=["bencha"]), managed=MANAGED, editor="coder")
    assert [(w.profile, w.by_agent) for w in wakes] == [("bencha", True)]


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
