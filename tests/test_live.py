"""Reconcile, tools, the editor rule and the wake-ups against a real private `annotary serve`."""

import json
import os
import shutil
import stat

import pytest
from conftest import make_profile

from annotary_hermes import accounts, enablement, server, state, tools, watcher

PLAN = "# Plan\n\nStep one: build the thing.\n\nStep two: test it.\n"


def owner_cli(*args, stdin=None):
    r = server.run_cli(server.owner_token(), [*args], stdin=stdin)
    assert r.returncode == 0, r.stderr
    return r


def members():
    return {m["handle"]: m for m in server.api(server.owner_token(), "GET", "/api/v1/members")["members"]}


def caller(profile, session="", surface="cli", cwd=""):
    return tools.Caller(profile=profile, session_key=session, surface=surface, cwd=cwd)


class Inbox:
    """Stands in for ctx.inject_message: records (profile, text, session_key)."""

    def __init__(self, accept=True):
        self.got, self.accept = [], accept

    def for_profile(self, profile):
        return lambda text, key: (self.got.append((profile, text, key)), self.accept)[1]


def watchers(inbox, *profiles):
    ws = [watcher.Watcher(p, inbox.for_profile(p)) for p in profiles]
    for w in ws:
        w._cursor(server.owner_token())  # start from the head, as a fresh gateway does
    return ws


def drain(ws):
    for w in ws:
        w.step(wait=0)


# ------------------------------------------------------------------ accounts

def test_reconcile_creates_one_member_per_profile_with_a_private_token(hermes):
    report = accounts.reconcile()
    assert set(report) == {"default", "coder", "bencha"}
    m = members()
    assert {"hermes", "coder", "bencha"} <= set(m)
    for pid in ("default", "coder", "bencha"):
        from annotary_hermes import paths
        p = paths.token_path(pid)
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert accounts.reconcile() == {}  # a second pass changes nothing


def test_rename_keeps_the_member_and_follows_the_title(hermes):
    accounts.reconcile()
    old = hermes / "profiles" / "coder"
    new = hermes / "profiles" / "dev-bot"
    shutil.move(old, new)
    (new / "profile.yaml").write_text("previous_names:\n  - coder\nui_meta:\n  hermes-bots:\n    title: Dev Bot\n")
    report = accounts.reconcile()
    assert "renamed from coder" in report["dev-bot"]
    st = state.load()
    assert st["members"]["dev-bot"]["handle"] == "coder" and "coder" not in st["members"]
    assert members()["coder"]["name"] == "Dev Bot"
    assert "dev-bot" not in members()


def test_deleted_profile_is_disabled_and_a_new_one_added(hermes):
    accounts.reconcile()
    old_tok = accounts.token_for("bencha")
    shutil.rmtree(hermes / "profiles" / "bencha")
    make_profile(hermes, "fresh")
    report = accounts.reconcile()
    assert report["bencha"].endswith("disabled") and report["fresh"] == "added @fresh"
    assert members()["bencha"].get("disabled_at") and not members()["fresh"].get("disabled_at")
    make_profile(hermes, "bencha")  # it comes back: the same Member, enabled, with a new Token
    report = accounts.reconcile()
    assert report["bencha"] == "profile back, @bencha enabled"
    assert not members()["bencha"].get("disabled_at") and "bencha-2" not in members()
    assert not state.load()["members"]["bencha"].get("disabled")
    new_tok = accounts.token_for("bencha")
    assert new_tok and new_tok != old_tok
    assert server.api(new_tok, "GET", "/api/v1/events?wait=0&limit=1") is not None
    with pytest.raises(server.ServerError) as e:  # enabling keeps the old Tokens revoked
        server.api(old_tok, "GET", "/api/v1/events?wait=0&limit=1")
    assert getattr(e.value, "status", None) == 401
    assert accounts.handles()["bencha"] == "bencha" and "bencha" in accounts.active_handles()
    out = tools.share(caller("bencha"), markdown="# Back\n", name="Back")  # works with its new Token
    assert state.load()["docs"][out["id"]]["editor"] == "bencha"
    assert accounts.reconcile() == {}


def test_default_profile_named_gets_its_own_handle(hermes):
    (hermes / "profile.yaml").write_text("display_name: Maia\n")
    accounts.reconcile()
    assert state.load()["members"]["default"]["handle"] == "maia"


# ------------------------------------------------------------------ tools + editor rule

def share(profile="coder", session="sess-coder", surface="cli"):
    return tools.share(caller(profile, session, surface), markdown=PLAN, name="Plan", message="first")


def test_a_shared_document_keeps_the_name_it_was_given(hermes):
    assert tools.share(caller("coder"), markdown="# x\n", name="Probe back")["name"] == "Probe back"
    assert tools.share(caller("coder"), markdown="# Q3 plan: v2 (draft)\n\nBody.\n")["name"] == "Q3 plan: v2 (draft)"
    odd = tools.share(caller("coder"), markdown="# y\n", name="--help/../x")
    assert odd["name"] == "help-..-x" and odd["id"]  # no option, no path, from a name


def test_share_records_editor_and_session_and_asks_once(hermes):
    out = share(surface="desktop")
    assert out["card"] == f'::annotary{{doc="{out["id"]}"}}'
    assert tools.WAKE_SETUP in out["setup_first"]
    doc = state.load()["docs"][out["id"]]
    assert (doc["editor"], doc["session_key"]) == ("coder", "sess-coder")
    again = tools.share(caller("coder", "sess-coder"), markdown="# Other\n", name="Other")
    assert tools.WAKE_SETUP not in again.get("setup_first", []) and "card" not in again


def test_only_the_editor_pushes_and_never_mid_review(hermes):
    doc = share()["id"]
    refused = tools.push_version(caller("bencha"), doc=doc, markdown=PLAN + "\nbencha\n")
    assert refused["refused"] and "@coder edits this Document" in refused["reason"]
    assert "note" not in refused  # nothing was pushed, so nothing may say it was
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Why step one?")
    mid = tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "\nv2\n")
    assert mid["refused"] and "review is open" in mid["reason"] and "note" not in mid
    owner_cli("act", doc, "send-back")
    ok = tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "\nv2\n", message="fix")
    assert ok["version"] == 2
    assert "answer each Thread you acted on" in ok["next"] and "Done in v2: " in ok["next"]
    th = tools.threads(caller("coder"), doc=doc)
    tid = th["threads"][0]["id"]
    tools.reply(caller("coder"), doc=doc, thread=tid, text="Fixed in v2.", resolve=True)
    assert tools.threads(caller("coder"), doc=doc)["threads"] == []


def test_handoff_moves_the_editor(hermes):
    doc = share()["id"]
    with pytest.raises(tools.ToolError):
        tools.handoff(caller("bencha"), doc=doc, to="@bencha")
    assert tools.handoff(caller("coder"), doc=doc, to="@bencha")["editor"] == "@bencha"
    assert tools.push_version(caller("coder"), doc=doc, markdown=PLAN + "x\n")["refused"]


# ------------------------------------------------------------------ wake-ups

def test_send_back_wakes_the_editors_sharing_session_and_comments_wake_nobody(hermes):
    accounts.reconcile()
    inbox = Inbox()
    ws = watchers(inbox, "default", "coder", "bencha")
    doc = share()["id"]
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Please explain step one.")
    drain(ws)
    assert inbox.got == []  # a plain Comment wakes nobody
    owner_cli("act", doc, "send-back")
    drain(ws)
    assert [(p, k) for p, _, k in inbox.got] == [("coder", "sess-coder")]
    text = inbox.got[0][1]
    assert "Send back" in text and "Please explain step one." in text and "annotary_push_version" in text


def test_a_desktop_backend_chat_is_woken_by_the_desktop_backend_and_a_gateway_chat_by_the_gateway(hermes):
    # A remote Hermes hosts Desktop chats in its dashboard, keyed by a bare session id the gateway
    # cannot route: injected from the gateway, the wake reached no chat and still read "woke".
    from annotary_hermes import docs
    accounts.reconcile()
    gw, desk = Inbox(), Inbox()
    ws = [watcher.Watcher("coder", gw.for_profile("coder")),
          watcher.Watcher("coder", desk.for_profile("coder"), host=docs.DESKTOP)]
    for w in ws:
        w._cursor(server.owner_token())
    remote = tools.share(tools.Caller(profile="coder", session_key="20261111_212221_fc90ed", surface="desktop",
                                      host=docs.DESKTOP), markdown=PLAN, name="Remote")["id"]
    local = share()["id"]
    owner_cli("act", remote, "send-back")
    owner_cli("act", local, "send-back")
    drain(ws)
    assert [k for _, _, k in desk.got] == ["20261111_212221_fc90ed"]
    assert [k for _, _, k in gw.got] == ["sess-coder"]
    log = [(r["doc"], r["outcome"], r["host"]) for r in state.load()["wake_log"]]
    assert sorted(log) == sorted([(remote, "woke", "desktop"), (local, "woke", "gateway")])  # one each, never two


def test_a_watcher_whose_host_is_not_live_reads_nothing(hermes):
    # `gateway restart` handing off to a service looks like the gateway but never hosts it.
    import threading
    accounts.reconcile()
    w = watcher.Watcher("coder", Inbox().for_profile("coder"), ready=lambda: False)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(0.5)
    w.stop.set()
    t.join(5)
    assert "coder" not in state.load()["cursors"]


def test_mention_wakes_only_the_named_bot_and_tells_it_not_to_push(hermes):
    accounts.reconcile()
    tools.list_docs(caller("bencha", "sess-bencha"))  # bencha has used Annotary from this session
    inbox = Inbox()
    ws = watchers(inbox, "coder", "bencha")
    doc = share()["id"]
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="@bencha what do you think?")
    drain(ws)
    assert [(p, k) for p, _, k in inbox.got] == [("bencha", "sess-bencha")]
    assert "Do not push" in inbox.got[0][1]


def test_agent_to_agent_mentions_are_capped(hermes):
    accounts.reconcile()
    tools.list_docs(caller("bencha", "sess-bencha"))
    inbox = Inbox()
    ws = watchers(inbox, "bencha")
    doc = share()["id"]
    tok = accounts.token_for("coder")
    for i in range(5):
        r = server.run_cli(tok, ["thread", "new", doc, "--document", "-m", "-"], stdin=f"@bencha ping {i}")
        assert r.returncode == 0, r.stderr
    drain(ws)
    assert len(inbox.got) == 3
    outcomes = [r["outcome"] for r in state.load()["wake_log"]]
    assert outcomes.count("capped") == 2


def test_wake_off_queues_a_notice_the_agent_sees_next_call(hermes):
    accounts.reconcile()
    inbox = Inbox(accept=False)  # inject_message refused: allow_gateway_injection is off
    ws = watchers(inbox, "coder")
    doc = share()["id"]
    owner_cli("act", doc, "approve")
    drain(ws)
    listed = tools.list_docs(caller("coder", "sess-coder"))
    assert [m["action"] for m in listed["missed_wakeups"]] == ["approve"]
    assert "missed_wakeups" not in tools.list_docs(caller("coder", "sess-coder"))


def test_secrets_are_mode_600_and_never_in_state(hermes):
    from annotary_hermes import paths
    assert stat.S_IMODE(os.stat(server.secrets_file()).st_mode) == 0o600
    share()
    text = (paths.app_dir() / "state.json").read_text()
    assert server.owner_token() not in text
    assert json.loads(server.secrets_file().read_text())["owner_password"] not in text


def test_stop_finds_the_server_whichever_binary_started_it(hermes, monkeypatch, tmp_path):
    other = tmp_path / "annotary"
    other.write_text("#!/bin/sh\n")  # a different binary path, as with ANNOTARY_HERMES_DEV_BINARY
    other.chmod(0o755)
    monkeypatch.setenv("ANNOTARY_HERMES_DEV_BINARY", str(other))
    assert server.stop()["stopped"] is True
    assert server.health(0.5) is None


# ------------------------------------------------------------------ review round 1

def test_threads_and_the_wake_digest_carry_reply_bodies(hermes):
    accounts.reconcile()
    doc = share()["id"]
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Root question?")
    owner_cli("thread", "reply", doc, "t1", "-m", "-", stdin="And a follow-up only in the reply.")
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Settled already.")
    owner_cli("thread", "resolve", doc, "t2")
    got = tools.threads(caller("coder"), doc="Plan")  # by Name
    assert [t["id"] for t in got["threads"]] == ["t1"]
    assert got["threads"][0]["replies"][0]["body"] == "And a follow-up only in the reply."
    every = tools.threads(caller("coder"), doc=doc, open_only=False)
    assert {t["id"]: t["resolved"] for t in every["threads"]} == {"t1": False, "t2": True}
    assert every["threads"][1]["replies"] == []
    inbox = Inbox()
    ws = watchers(inbox, "coder")
    owner_cli("act", doc, "send-back")
    drain(ws)
    assert "And a follow-up only in the reply." in inbox.got[0][1]


def test_markdown_shares_with_the_same_name_are_separate_documents(hermes):
    first = share()
    owner_cli("thread", "new", first["id"], "--document", "-m", "-", stdin="Reviewing the first one.")
    second = share()  # same name and heading
    assert second["id"] != first["id"] and second["version"] == 1
    assert server.api(server.owner_token(), "GET", f"/api/v1/docs/{first['id']}")["version"] == 1
    owner_cli("act", first["id"], "send-back")
    ok = tools.push_version(caller("coder"), doc=first["id"], markdown=PLAN + "\nv2 of the first\n")
    assert ok["id"] == first["id"] and ok["version"] == 2
    paths_ = {state.load()["docs"][d]["path"] for d in (first["id"], second["id"])}
    assert len(paths_) == 2


def test_sharing_a_bound_file_follows_the_editor_and_review_rules(hermes, tmp_path):
    (tmp_path / "plan.md").write_text(PLAN)
    doc = tools.share(caller("coder", cwd=str(tmp_path)), path="plan.md")["id"]
    (tmp_path / "plan.md").write_text(PLAN + "\nbencha's edit\n")
    refused = tools.share(caller("bencha", cwd=str(tmp_path)), path="plan.md")
    assert refused["refused"] and "@coder edits this Document" in refused["reason"]
    assert "note" not in refused  # nothing was pushed, so nothing may say it was
    assert state.load()["docs"][doc]["editor"] == "coder"
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Wait for me.")
    mid = tools.share(caller("coder", cwd=str(tmp_path)), path="plan.md")
    assert mid["refused"] and "review is open" in mid["reason"] and "note" not in mid
    owner_cli("act", doc, "send-back")
    ok = tools.share(caller("coder", cwd=str(tmp_path)), path="plan.md")
    assert ok["id"] == doc and ok["version"] == 2
    assert ok["note"] == f"plan.md is already the Document {doc}: this pushed a new Version of it."


def test_missed_wakeups_ride_on_every_tool(hermes):
    accounts.reconcile()
    doc = share()["id"]
    def queue(st):
        st["pending"]["coder"] = [{"reason": "review", "doc": doc, "action": "approve"}]
    state.update(queue)
    assert tools.threads(caller("coder"), doc=doc)["missed_wakeups"][0]["action"] == "approve"
    assert "missed_wakeups" not in tools.threads(caller("coder"), doc=doc)


def test_handoff_and_editor_refuse_disabled_members(hermes):
    from annotary_hermes import docs as docs_mod
    accounts.reconcile()
    doc = share()["id"]
    shutil.rmtree(hermes / "profiles" / "bencha")
    accounts.reconcile()
    with pytest.raises(tools.ToolError, match="not an active Bot"):
        tools.handoff(caller("coder"), doc=doc, to="@bencha")
    with pytest.raises(ValueError):
        docs_mod.set_editor_for_handle(doc, "@bencha")
    assert state.load()["docs"][doc]["editor"] == "coder"


def test_a_running_server_on_a_stale_binary_gets_the_pinned_one(hermes, monkeypatch):
    from annotary_hermes import install
    monkeypatch.delenv(install.DEV_BINARY_ENV, raising=False)
    install.bin_dir().mkdir(parents=True, exist_ok=True)
    (install.bin_dir() / "SHA256").write_text("stale-pin\n")  # what a new pin looks like after an upgrade
    assert not install.installed()["ok"]
    out = server.ensure_running()
    assert out["outcome"] == "started" and install.installed()["ok"]
    assert out["health"]["version"] == install.VERSION.lstrip("v")


def running_command() -> str:
    import subprocess
    return subprocess.run(["ps", "-ww", "-p", str(server.server_pid()), "-o", "command="], capture_output=True,
                          text=True).stdout.strip()


def test_a_dev_build_that_reports_the_pinned_version_is_replaced(hermes, monkeypatch, tmp_path):
    from annotary_hermes import install
    dev = tmp_path / "dev" / "annotary"
    dev.parent.mkdir()
    shutil.copy2(install.bin_path(), dev)  # same version string, a different binary
    server.stop()
    monkeypatch.setenv(install.DEV_BINARY_ENV, str(dev))
    assert server.ensure_running()["outcome"] == "started"
    assert running_command().startswith(f"{dev} serve ")
    monkeypatch.delenv(install.DEV_BINARY_ENV)  # the override is taken out
    out = server.ensure_running()
    assert out["outcome"] == "started" and out["health"]["version"] == install.VERSION.lstrip("v")
    assert running_command().startswith(f"{install.bin_path()} serve ")


def test_a_current_server_is_left_alone(hermes):
    pid = server.server_pid()
    assert server.ensure_running()["outcome"] == "running"
    assert server.server_pid() == pid


def test_the_dev_override_never_triggers_a_reinstall(hermes, monkeypatch, tmp_path):
    from annotary_hermes import install
    dev = tmp_path / "annotary"
    dev.write_text("#!/bin/sh\n")
    dev.chmod(0o755)
    monkeypatch.setenv(install.DEV_BINARY_ENV, str(dev))
    pid = server.server_pid()
    assert server.ensure_running()["outcome"] == "running" and server.server_pid() == pid


def test_the_wake_digest_marks_threads_waiting_for_an_answer(hermes):
    accounts.reconcile()
    doc = share()["id"]
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Survey or interviews?")
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="Add a rollback step.")
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="@bencha which step matters most?")
    owner_cli("thread", "new", doc, "--document", "-m", "-", stdin="@coder and @bencha: agree?")
    tools.reply(caller("coder"), doc=doc, thread="t2", text="Done in v1 already: step 4.")
    digest = watcher._thread_digest(server.owner_token(), doc, None, "coder")
    lines = {line.split(" ")[1]: line for line in digest.splitlines() if line.startswith("- t")}
    assert "(waiting for your answer)" in lines["t1"] and "(waiting for your answer)" not in lines["t2"]
    # A question to another Bot is not the editor's to answer.
    assert "(for @bencha to answer)" in lines["t3"] and "(waiting for your answer)" in lines["t4"]


def test_a_profile_without_annotary_is_reported_once_and_never_made_editor(hermes):
    from annotary_hermes import docs as docs_mod
    accounts.reconcile()
    home = make_profile(hermes, "fresh", annotary=False)  # `hermes profile create` after install
    report = accounts.reconcile()
    assert report["fresh"] == "added @fresh; " + enablement.SAY[enablement.OFF]
    assert accounts.reconcile() == {}  # said once, not on every pass
    doc = share()["id"]
    with pytest.raises(tools.ToolError, match="Annotary is off in that profile"):
        tools.handoff(caller("coder"), doc=doc, to="@fresh")
    with pytest.raises(ValueError, match="Annotary is off"):
        docs_mod.set_editor_for_handle(doc, "@fresh")
    assert enablement.link_plugin("fresh") == "linked"  # what `hermes annotary enable --all` does,
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - annotary\n")  # with Hermes's enable
    assert accounts.reconcile() == {"fresh": "Annotary is on in this profile"}
    assert tools.handoff(caller("coder"), doc=doc, to="@fresh")["editor"] == "@fresh"


def test_a_cloned_profile_with_its_own_copy_is_reported(hermes):
    accounts.reconcile()
    home = make_profile(hermes, "bot", annotary=False)  # Desktop's Bot Mode clones default
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - annotary\n")
    copy = home / "plugins" / "annotary"
    (copy / "annotary_hermes").mkdir(parents=True)
    (copy / "plugin.yaml").write_text("name: annotary\n")
    assert accounts.reconcile()["bot"] == "added @bot; " + enablement.SAY[enablement.COPY]
    assert enablement.link_plugin("bot") == "replaced its own copy with a link"
    assert accounts.reconcile() == {"bot": "Annotary is on in this profile"}


def test_dollar_amounts_render_as_text_not_math(hermes):
    # The pinned renderer must not let a `$` followed by a digit close inline math (#27).
    import urllib.request
    from annotary_hermes import paths
    accounts.reconcile()
    body = "# Price\n\nCost per pack is maybe $1.00–1.25 (a batch is 72 cookies out of a ~$120 shop).\n"
    doc = tools.share(caller("coder"), markdown=body, name="Price")["id"]
    req = urllib.request.Request(paths.server_url() + f"/api/v1/docs/{doc}/versions/1/html",
                                 headers={"Authorization": f"Bearer {server.owner_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode()
    assert "<math" not in html and "$1.00–1.25" in html and "~$120" in html, html


def test_a_narrow_terminal_still_finds_and_upgrades_our_server(hermes, monkeypatch):
    # #34: procps cuts `ps` output at $COLUMNS; the server's command line is longer than 80.
    from annotary_hermes import install
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv(install.DEV_BINARY_ENV, raising=False)
    pid = server.server_pid()
    assert server._is_our_server(pid)
    (install.bin_dir() / "SHA256").write_text("stale-pin\n")
    out = server.ensure_running()
    assert out["outcome"] == "started" and server.server_pid() != pid
