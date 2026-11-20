"""Questions (a decisions table, a Question asked on a comment) and Markup (a drawing on a Comment),
from annotary v0.8.0, through the tools, the wake-ups, the page backend and the embed bridge.

All against a real `annotary serve` (the `hermes` fixture). coder edits; the owner is the person.
"""

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest
from test_comment import Inbox, caller, owner_cli, plugin_module, FakeCtx

from annotary_hermes import accounts, bridge, docs, paths, server, tools, watcher

PLAN = """# Host plan

## D1. Where it runs

- A. The existing box.
- B. A new VM.

## D2. Which database

Option A: SQLite. Option B: Postgres.

| Decision | Options | Recommended | Decided |
|---|---|---|---|
| D1 | A, B | A | |
| D2 | A, B | B | |
"""


def png(w=40, h=20) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([200, 30, 30] * w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def post_markup(tmp_path, doc, *, thread=None, body=None, anchor="3:0-3:20"):
    """The owner draws, as the app does: a PNG and its strokes, through the CLI's upload."""
    (tmp_path / "m.png").write_bytes(png())
    (tmp_path / "m.json").write_text(json.dumps({"strokes": [{"color": "#dd0000", "width": 3,
                                                               "points": [[1, 1, 0], [30, 12, 0.3]]}]}))
    what = ["thread", "reply", doc, thread] if thread else ["thread", "new", doc, anchor]
    args = [*what, "--markup", str(tmp_path / "m.png"), "--strokes", str(tmp_path / "m.json")]
    owner_cli(*args, *(["-m", body] if body else []), "--json")


@pytest.fixture()
def doc(hermes):
    accounts.reconcile()
    return tools.share(caller("coder"), markdown=PLAN, name="Host plan", message="first")["id"]


def answer(doc, key, option):
    owner_cli("answer", doc, key, option)


def watching(profile="coder"):
    inbox = Inbox()
    w = watcher.Watcher(profile, inbox.for_profile(profile))
    w._cursor(server.owner_token())
    return inbox, w


# ------------------------------------------------------------------ reading and pushing the decisions table


def test_read_hands_back_the_answers_in_the_decided_cells_and_says_so(doc):
    assert "answers_filled" not in tools.read(caller("coder"), doc=doc)
    answer(doc, "D1", "B")
    out = tools.read(caller("coder"), doc=doc)
    assert "| D1 | A, B | A | B (@" in out["text"] and out["answers_filled"] == 1
    assert "push" in out["answers_note"] and "refused" in out["answers_note"]


def test_a_comment_is_anchored_on_the_versions_own_bytes_not_the_filled_text(doc):
    answer(doc, "D1", "B")
    out = tools.comment(caller("bencha"), doc=doc, quote="D1 | A, B | A | |", body="Why A?")
    assert "refused" not in out, out
    shown = json.loads(owner_cli("thread", "show", doc, out["id"], "--json").stdout)[0]
    assert shown["anchor"]["original"]["exact"] == "D1 | A, B | A | |"


def test_a_push_that_drops_an_answer_is_refused_with_the_rows_to_put_in(doc, monkeypatch):
    answer(doc, "D1", "B")
    seen = []
    real = server.run_cli
    monkeypatch.setattr(server, "run_cli", lambda tok, args, **kw: (seen.append(args), real(tok, args, **kw))[1])
    out = tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "\nMore.\n", review_over=True)
    assert out["refused"] is True and "rows" in out and "annotary_read" in out["reason"]
    (row,) = out["rows"]
    assert row["key"] == "D1" and row["text"].startswith("| D1 | A, B | A | B (@")
    assert not any("--discard-answers" in a for a in seen)
    assert server.api(server.owner_token(), "GET", f"/api/v1/docs/{doc}")["version"] == 1
    # The agent puts the row in (or starts from annotary_read's text) and pushes again.
    fixed = tools.read(caller("coder"), doc=doc)["text"] + "\nMore.\n"
    pushed = tools.push_version(caller("coder"), doc=doc, markdown=fixed, review_over=True)
    assert pushed.get("version") == 2, pushed
    line = docs.questions_line(server.owner_token(), doc)
    assert "D1=decided" in line and "D2=-" in line


def test_a_share_of_a_bound_file_that_drops_an_answer_is_refused_the_same_way(doc):
    answer(doc, "D2", "A")
    file = Path(docs.info(doc)["path"])
    file.write_text(PLAN + "\nMore.\n")  # edited, its Decided cells still empty
    out = tools.share(caller("coder"), path=str(file))
    assert out.get("refused") is True and [r["key"] for r in out["rows"]] == ["D2"], out


# ------------------------------------------------------------------ a Question asked on a comment


def test_a_comment_with_options_asks_a_question_the_threads_tool_shows_with_its_answer(doc):
    out = tools.comment(caller("bencha"), doc=doc, quote="Option A: SQLite.", body="Which one for now?",
                        options=["SQLite", "Postgres"])
    assert "refused" not in out and "asked" in out, out
    tid = out["id"]
    answer(doc, tid, "B")
    answer(doc, "D1", "A")
    got = tools.threads(caller("coder"), doc=doc)
    (t,) = [t for t in got["threads"] if t["id"] == tid]
    assert t["question"] == tid and t["options"] == {"A": "SQLite", "B": "Postgres"} and t["answer"] == "B"
    assert got["questions"].startswith(f"D1=A D2=- {tid}=B") and "- unanswered" in got["questions"]
    assert "questions" not in got["doc"]


@pytest.mark.parametrize("options,why", [(["Only"], "2 to 6"), ([str(i) for i in range(7)], "2 to 6"),
                                         (["Yes", "yes"], "differ"), (["Yes", "x" * 81], "short label"),
                                         (["Yes", "--json"], "short label"), ("Yes,No", "list")])
def test_options_are_two_to_six_short_distinct_labels(doc, options, why):
    with pytest.raises(tools.ToolError, match=why):
        tools.comment(caller("bencha"), doc=doc, quote="Option A: SQLite.", body="Which?", options=options)


def test_threads_has_no_questions_line_without_questions(hermes):
    accounts.reconcile()
    d = tools.share(caller("coder"), markdown="# Note\n\nPlain.\n", name="Note")["id"]
    tools.comment(caller("bencha"), doc=d, quote="Plain.", body="Fine.")
    got = tools.threads(caller("coder"), doc=d)
    assert "questions" not in got and "question" not in got["threads"][0] and "markup" not in got


# ------------------------------------------------------------------ wake-ups (D5 as written)


def test_an_answer_wakes_no_bot_and_does_not_open_a_review(doc):
    inbox, w = watching()
    answer(doc, "D1", "B")
    answer(doc, "D2", "A")
    assert w.step(wait=0) == [] and inbox.got == []
    assert docs.review_is_open(doc) is False
    out = tools.push_version(caller("coder"), doc=doc, markdown=tools.read(caller("coder"), doc=doc)["text"])
    assert out.get("version") == 2, out  # not refused as mid-review


@pytest.mark.parametrize("action,advice", [("send-back", "Start from annotary_read's text"),
                                           ("approve", "Record their answers")])
def test_send_back_and_approve_wake_the_editor_with_the_answers(doc, action, advice):
    inbox, w = watching()
    answer(doc, "D1", "B")
    owner_cli("act", doc, action)
    (rec,) = w.step(wait=0)
    assert rec["outcome"] == "woke"
    (_, text, _), = inbox.got
    assert "Questions and answers: D1=B D2=-" in text and advice in text


def test_a_wake_without_questions_says_nothing_about_them(hermes):
    accounts.reconcile()
    d = tools.share(caller("coder"), markdown="# Note\n\nPlain.\n", name="Note")["id"]
    inbox, w = watching()
    owner_cli("act", d, "send-back")
    w.step(wait=0)
    (_, text, _), = inbox.got
    assert "Questions" not in text and "Decided" not in text


# ------------------------------------------------------------------ Markup


def test_threads_and_the_digest_say_which_threads_hold_a_drawing(doc, tmp_path):
    post_markup(tmp_path, doc)
    post_markup(tmp_path, doc, thread="t1", body="and this")
    got = tools.threads(caller("coder"), doc=doc)
    (t,) = got["threads"]
    assert t["markup"] is True and t["replies"][0]["markup"] is True and "annotary_markup" in got["markup"]
    digest = watcher._thread_digest(accounts.token_for("coder"), doc, None, "coder")
    assert digest.count(watcher.MARKUP_TAG) == 2


def test_the_markup_tool_returns_the_image_and_names_the_saved_file_and_the_text(doc, tmp_path):
    post_markup(tmp_path, doc, body="cross this out")
    post_markup(tmp_path, doc, thread="t1")
    out = tools.markup(caller("coder"), doc=doc, thread="t1")
    assert out["_multimodal"] is True
    text, *images = out["content"]
    assert text["type"] == "text" and len(images) == 2
    assert all(i["type"] == "image_url" and i["image_url"]["url"].startswith("data:image/png;base64,") for i in images)
    assert base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) == png()
    folder = paths.markup_dir("coder") / doc
    saved = sorted(folder.glob("*.png"))
    assert [p.name for p in saved] == ["t1.1.png", "t1.png"]
    for p in saved:
        assert str(p) in out["text_summary"]
    assert '"## D1. Where it runs"' in out["text_summary"] and "cross this out" in out["text_summary"]
    assert "vision_analyze" in out["text_summary"]
    assert not str(folder).startswith(str(Path.home() / ".annotary"))


def test_the_markup_tool_on_a_thread_without_one_says_so(doc):
    tools.comment(caller("bencha"), doc=doc, quote="Option A: SQLite.", body="Hm.")
    out = tools.markup(caller("coder"), doc=doc, thread="t1")
    assert out["markup"] is None and "no drawing" in out["note"]


def test_the_markup_folder_stays_bounded(doc, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "MARKUP_KEEP", 1)
    post_markup(tmp_path, doc)
    post_markup(tmp_path, doc, thread="t1", body="more")
    tools.markup(caller("coder"), doc=doc, thread="t1")
    assert len(list(paths.markup_dir("coder").rglob("*.png"))) == 1


def test_the_handler_passes_the_multimodal_result_through_and_json_encodes_the_rest(doc, tmp_path):
    post_markup(tmp_path, doc)
    ctx = FakeCtx()
    plugin_module().register(ctx)
    got = ctx.tools["annotary_markup"]["handler"]({"doc": doc, "thread": "t1"})
    assert isinstance(got, dict) and got["_multimodal"] is True and isinstance(got["content"], list)
    assert isinstance(ctx.tools["annotary_read"]["handler"]({"doc": doc}), str)
    err = ctx.tools["annotary_markup"]["handler"]({"doc": doc, "thread": "7"})
    assert json.loads(err) == {"error": "thread must be a Thread id like t3"}


def test_missed_wakeups_reach_a_multimodal_result_as_text(doc, tmp_path):
    from annotary_hermes import state
    post_markup(tmp_path, doc)

    def miss(st):
        st["pending"]["coder"] = [{"reason": "review", "doc": doc, "by": "owner", "action": "approve"}]
    state.update(miss)
    out = tools.markup(caller("coder"), doc=doc, thread="t1")
    assert "missed_wakeups" in out["content"][-1]["text"] and "missed_wakeups" in out["text_summary"]
    assert "missed_wakeups" not in out


# ------------------------------------------------------------------ the page: backend and embed render


def _plugin_api():
    from test_size_report import _plugin_api as load
    return load()


def test_the_doc_route_carries_the_questions_only_when_there_are_some(doc, hermes):
    api = _plugin_api()
    answer(doc, "D1", "B")
    d = api._doc(doc)
    assert [q["key"] for q in d["questions"]] == ["D1", "D2"]
    assert d["questions"][0]["options"] == ["A", "B"] and d["questions"][0]["answers"][0]["option"] == "B"
    plain = tools.share(caller("coder"), markdown="# Note\n\nPlain.\n", name="Note")["id"]
    assert "questions" not in api._doc(plain)


def test_the_embed_render_has_the_question_controls_and_the_markup(doc, tmp_path):
    asked = tools.comment(caller("bencha"), doc=doc, quote="Option A: SQLite.", body="Which first?",
                          options=["SQLite", "Postgres"])["id"]
    post_markup(tmp_path, doc)
    r = bridge.request({"method": "GET", "path": f"/d/{doc}", "headers": {"Accept": "text/html"}})
    assert r["status"] == 200, r["status"]
    page = r["body"]
    for mark in ("cd-qrow", "cd-qradio", "cd-qcell", 'id="cd-qaccept"', 'id="cd-qsum"', "data-cd-mk"):
        assert mark in page, mark
    # Answering goes through the bridge as the frame sends it (a PUT with a JSON body).
    v = server.api(server.owner_token(), "GET", f"/api/v1/docs/{doc}")["version"]
    for key, option in (("D1", "B"), (asked, "A")):
        res = bridge.request({"method": "PUT", "path": f"/api/v1/docs/{doc}/questions/{key}/answer",
                              "headers": {"Content-Type": "application/json"},
                              "body": json.dumps({"option": option, "version": v})})
        assert res["status"] == 200, res
    line = docs.questions_line(server.owner_token(), doc)
    assert "D1=B" in line and f"{asked}=A" in line
    # The Markup image itself, as the frame fetches it (binary, under the bridge's cap).
    (mk,) = [t["markup"]["image"] for t in server.api(server.owner_token(), "GET", f"/api/v1/docs/{doc}/threads")["threads"]
             if t.get("markup")]
    img = bridge.request({"method": "GET", "path": f"/api/v1/docs/{doc}/markups/{mk}", "binary": True})
    assert img["status"] == 200 and base64.b64decode(img["body"]) == png()
