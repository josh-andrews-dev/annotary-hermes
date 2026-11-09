"""The live review loop's own checks (scripts/project/live_loop.py): what counts as done."""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from annotary_hermes import paths, server, state, tools

_spec = importlib.util.spec_from_file_location(
    "live_loop", Path(__file__).resolve().parents[1] / "scripts" / "project" / "live_loop.py")
live_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_loop)


def thread(tid, *replies, resolved=True):
    return {"id": tid, "resolved": resolved, "replies": [{"author": a, "body": b} for a, b in replies]}


def test_a_reply_cites_the_version_it_points_to():
    for body in ("Added as step 4 in v2.", "Fixed in Version 2", "see version 2: dated", "V2 has it"):
        assert live_loop.cites_version(body, 2), body
    for body in ("Added a rollback step.", "v12 has it", "version 20", "v2x"):
        assert not live_loop.cites_version(body, 2), body


def test_done_needs_one_push_a_cited_reply_on_each_thread_and_both_resolved():
    good = [thread("t1", ("coder", "Added in v2.")), thread("t2", ("coder", "Dated in Version 2."))]
    assert live_loop.loop_status(2, good, "coder")["done"]
    assert not live_loop.loop_status(1, good, "coder")["done"]  # never pushed
    assert not live_loop.loop_status(3, good, "coder")["done"]  # pushed twice
    unresolved = [good[0], thread("t2", ("coder", "Dated in v2."), resolved=False)]
    assert not live_loop.loop_status(2, unresolved, "coder")["done"]
    uncited = [good[0], thread("t2", ("coder", "Done."))]
    status = live_loop.loop_status(2, uncited, "coder")
    assert not status["done"] and status["threads"][1] == {
        "thread": "t2", "replied": True, "cites_version": False, "resolved": True}
    someone_else = [good[0], thread("t2", ("owner", "I fixed it in v2 myself."))]
    assert not live_loop.loop_status(2, someone_else, "coder")["done"]
    assert not live_loop.loop_status(2, good[:1], "coder")["done"]  # a Thread missing


def done(code=1, out="", err=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


def test_a_failed_step_stops_with_stderr_and_never_stdout():
    live_loop.checked(done(0, out="fine"), "step")
    with pytest.raises(live_loop.StepFailed) as e:
        live_loop.checked(done(out="owner-token-here", err="  no such doc\n"), "Send back")
    assert str(e.value) == "Send back: no such doc"
    with pytest.raises(live_loop.StepFailed, match="exit 3"):
        live_loop.checked(done(3), "Send back")


def test_the_owner_review_stops_at_the_first_failed_step(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "run_cli", lambda tok, args, **kw: (calls.append(args), done(err="refused"))[1])
    with pytest.raises(live_loop.StepFailed, match="refused"):
        live_loop.send_back("tok", "doc1")
    assert len(calls) == 1


def test_only_this_profiles_new_documents_count():
    docs = {"old": {"editor": "coder"}, "new": {"editor": "coder"}, "other": {"editor": "bencha"}, "bare": {}}
    assert live_loop.new_documents(docs, {"old"}, "coder") == ["new"]


def share_as(profile, name):
    made = tools.share(tools.Caller(profile=profile, session_key="s", surface="cli", cwd=""),
                       markdown=f"# {name}\n", name=name)
    return made["id"]


def purged(doc):
    return server.run_cli(server.owner_token(), ["restore", doc]).returncode != 0


def test_clean_up_removes_only_what_this_run_made(hermes):
    earlier = share_as("coder", "Earlier")
    before = set(state.load()["docs"])
    mine, also_mine, theirs = share_as("coder", "Mine"), share_as("coder", "Mine too"), share_as("bencha", "Theirs")
    assert live_loop.clean_up(server.owner_token(), "coder", before) == []

    docs = state.load()["docs"]
    shares = paths.shares_dir("coder")
    for doc in (mine, also_mine):
        assert purged(doc) and doc not in docs and not (shares / doc).exists()
    for doc, who in ((earlier, "coder"), (theirs, "bencha")):
        assert doc in docs and (paths.shares_dir(who) / doc).exists()
        assert server.api(server.owner_token(), "GET", f"/api/v1/docs/{doc}")["id"] == doc


def test_a_document_that_cannot_be_removed_keeps_its_record(hermes, monkeypatch):
    before = set(state.load()["docs"])
    doc = share_as("coder", "Stuck")
    real = server.run_cli
    monkeypatch.setattr(server, "run_cli", lambda tok, args, **kw: done(err="nope") if args[0] == "purge"
                        else real(tok, args, **kw))
    assert live_loop.clean_up(server.owner_token(), "coder", before) == [doc]
    assert doc in state.load()["docs"] and (paths.shares_dir("coder") / doc).exists()


def test_a_session_runs_in_its_folder_and_closes_its_log(tmp_path):
    folder, log = tmp_path / "work", tmp_path / "screen.log"
    folder.mkdir()
    sess = live_loop.Session(["sh", "-c", "pwd -P; sleep 30"], log, str(folder))
    for _ in range(100):
        if str(folder.resolve()) in log.read_text():
            break
        time.sleep(0.1)
    sess.close()
    assert str(folder.resolve()) in log.read_text()
    assert sess.log.closed


class FakeSession:
    """Stands in for the pty: the "agent" shares a Document as soon as it is asked."""

    made = None

    def __init__(self, argv, log, cwd):
        FakeSession.cwd, self.closed = cwd, False
        assert Path(cwd).is_dir()

    def type(self, text):
        FakeSession.made = share_as("coder", "Wiki move")

    def close(self):
        self.closed = True


def test_a_failed_review_fails_the_run_at_once_and_still_cleans_up(hermes, monkeypatch, capsys):
    real = server.run_cli
    monkeypatch.setattr(server, "run_cli", lambda tok, args, **kw: done(out=tok, err="act refused")
                        if args[0] == "act" else real(tok, args, **kw))
    monkeypatch.setattr(live_loop, "Session", FakeSession)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["live_loop", "--profile", "coder", "--timeout", "30", "--label", "t"])
    started = time.time()
    assert live_loop.main() == 1
    assert time.time() - started < 25  # not the poll for the agent, which runs to the timeout

    out = capsys.readouterr()
    report = json.loads(out.out)
    assert report["done"] is False and report["error"] == "Send back: act refused"
    assert server.owner_token() not in out.out + out.err
    monkeypatch.setattr(server, "run_cli", real)
    assert purged(FakeSession.made) and FakeSession.made not in state.load()["docs"]
    assert not (paths.shares_dir("coder") / FakeSession.made).exists()
    assert not Path(FakeSession.cwd).exists()


@pytest.mark.parametrize("agent, left, code", [(0, [], 0), (0, ["doc1"], 1), (1, [], 1)])
def test_the_exit_code_needs_the_agent_done_and_nothing_left_behind(hermes, monkeypatch, agent, left, code):
    monkeypatch.setattr(live_loop, "Session", FakeSession)
    monkeypatch.setattr(live_loop, "run_loop", lambda *a: agent)
    monkeypatch.setattr(live_loop, "clean_up", lambda *a: left)
    monkeypatch.setattr(sys, "argv", ["live_loop", "--profile", "coder"])
    assert live_loop.main() == code
