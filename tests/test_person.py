"""The person's own name: a placeholder on a service account, the first-share setup steps, and
annotary_set_name, against a real private `annotary serve`."""

import json
from pathlib import Path

from annotary_hermes import accounts, server, state, tools


def caller(profile, session="", surface="desktop"):
    return tools.Caller(profile=profile, session_key=session, surface=surface)


def members():
    return {m["handle"]: m for m in server.api(server.owner_token(), "GET", "/api/v1/members")["members"]}


def me():
    return server.api(server.owner_token(), "GET", "/api/v1/me")


def test_a_service_account_install_makes_the_person_a_placeholder_not_the_bots_name(hermes_cloud):
    accounts.reconcile()
    assert server.owner_handle() == "owner" and not server.owner_named()
    assert members()["owner"]["name"] == "Owner"
    # The default Bot keeps its own name, instead of becoming @hermes-agent beside a person called @hermes.
    assert accounts.handle_of("default") == "hermes"


def test_a_named_os_user_is_the_person_and_is_never_asked(hermes_named):
    assert server.owner_named() and server.owner_handle() == "rowan"
    out = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    assert not any("annotary_set_name" in s for s in out.get("setup_first", []))


def test_the_first_share_leads_with_setup_and_asks_the_name_once(hermes_cloud):
    first = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    assert first["setup_first"] == [tools.PAGE_SETUP, tools.NAME_SETUP.format(handle="owner"), tools.WAKE_SETUP]
    assert "Start your reply" in first["setup_how"]
    again = tools.share(caller("coder"), markdown="# Other\n", name="Other")
    assert again["setup_first"] == [tools.PAGE_SETUP]  # the page step stays until the page loads; the rest are asked once
    tools.record_page_seen()
    done = tools.share(caller("coder"), markdown="# Third\n", name="Third")
    assert "setup_first" not in done and "setup_how" not in done


def test_naming_gives_the_person_a_real_handle_and_keeps_the_server_closed(hermes_cloud):
    doc = tools.share(caller("coder"), markdown="# Plan\n\nStep one.\n", name="Plan")["id"]
    r = server.run_cli(server.owner_token(), ["thread", "new", doc, "--document", "-m", "First thought"])
    assert r.returncode == 0, r.stderr
    old_token = server.owner_token()
    out = tools.set_name(caller("coder"), name="  Rowan  ")
    assert (out["handle"], out["name"]) == ("rowan", "Rowan") and "@mention them as @rowan" in out["said"]
    assert server.owner_handle() == "rowan" and server.owner_named() and server.previous_owners() == ["owner"]
    assert (me()["handle"], me()["role"]) == ("rowan", "owner")
    m = members()
    assert m["owner"]["name"] == "Rowan" and m["owner"]["disabled_at"]
    try:  # the placeholder's Token no longer works
        server.api(old_token, "GET", "/api/v1/me")
        raise AssertionError("the placeholder's Token still works")
    except server.ServerError:
        pass
    assert server.health()["password_set"] is True  # loopback trust stays closed
    sec = json.loads(server.secrets_file().read_text())
    assert sec["owner_password"] and sec["owner_token"] != old_token
    # The placeholder's Comment keeps its author, whose display name is now the person's.
    threads = server.api(server.owner_token(), "GET", f"/api/v1/docs/{doc}/threads")["threads"]
    assert threads and threads[0]["author"] == "owner"  # the card shows this Member's display name, now Rowan
    steps = tools.share(caller("bencha"), markdown="# B\n", name="B").get("setup_first", [])
    assert not any("annotary_set_name" in step for step in steps)  # named now: no profile asks again


def test_a_second_name_changes_only_the_display_name(hermes_cloud):
    tools.set_name(caller("coder"), name="Rowan")
    out = tools.set_name(caller("coder"), name="Rowan A.")
    assert (out["handle"], out["name"]) == ("rowan", "Rowan A.") and "@mention" not in out["said"]
    assert server.owner_handle() == "rowan" and members()["rowan"]["name"] == "Rowan A."


def test_a_name_that_is_a_bots_handle_gets_a_free_one(hermes_cloud):
    accounts.reconcile()
    assert tools.set_name(caller("coder"), name="Hermes")["handle"] == "hermes-2"
    assert accounts.handle_of("default") == "hermes"


def test_a_name_without_latin_letters_keeps_the_handle(hermes_cloud):
    out = tools.set_name(caller("coder"), name="王伟")
    assert (out["handle"], out["name"]) == ("owner", "王伟") and "handle stays" in out["said"]
    assert server.owner_named()


def test_a_bad_name_is_refused(hermes_cloud):
    for bad in ("", "   ", "x" * 65):
        out = None
        try:
            out = tools.set_name(caller("coder"), name=bad)
        except tools.ToolError as e:
            assert "1 to 64" in str(e)
        assert out is None
    assert server.owner_handle() == "owner" and not server.owner_named()


def test_an_install_from_before_the_flag_counts_as_named_unless_its_handle_is_a_service_account(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for handle, named in (("hermes", False), ("root", False), ("rowan", True)):
        server.update_secrets({"owner_handle": handle, "owner_token": "x"})
        assert server.owner_named() is named, handle
    server.update_secrets({"owner_named": True})
    assert server.owner_named() is True


def test_list_names_the_person(hermes_cloud):
    assert tools.list_docs(caller("coder"))["person"] == {"handle": "@owner", "name": "Owner", "named": False}


def test_page_seen_is_recorded(hermes_cloud):
    assert not state.load().get("page_seen_at")
    tools.record_page_seen()
    assert state.load()["page_seen_at"] > 0


def test_the_cli_names_the_person(hermes_cloud, capsys):
    import argparse

    from annotary_hermes import cli
    assert cli.name(argparse.Namespace(name=["Rowan", "Lee"])) == 0
    assert "You are @rowan-lee, shown as Rowan Lee. @owner is retired." in capsys.readouterr().out


def test_wake_ups_already_allowed_are_not_asked(hermes_cloud):
    c = tools.Caller(profile="coder", surface="desktop", injection_allowed=True)
    assert tools.WAKE_SETUP not in tools.share(c, markdown="# Plan\n", name="Plan")["setup_first"]


def test_a_profile_running_its_own_copy_is_a_setup_step_once(hermes_cloud):
    from conftest import make_profile
    import shutil
    accounts.reconcile()
    here = hermes_cloud / "profiles" / "bencha" / "plugins" / "annotary"
    here.unlink()
    shutil.copytree(hermes_cloud / "plugins" / "annotary", here)  # a cloned profile's own copy,
    (here / "__init__.py").write_text("# an older version\n")  # since updated in default
    first = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")["setup_first"]
    assert tools.PROFILES_SETUP.format(profiles="bencha") in first
    assert tools.PROFILES_SETUP.format(profiles="bencha") not in tools.share(
        caller("coder"), markdown="# B\n", name="B").get("setup_first", [])


def test_naming_finishes_on_a_retry_after_failing_before_the_switch(hermes_cloud, monkeypatch):
    real = server.api
    calls = {"n": 0}

    def flaky(tok, method, path, body=None, **kw):
        if path == "/api/v1/settings/password" and not calls["n"]:
            calls["n"] += 1
            raise server.ServerError("boom")
        return real(tok, method, path, body, **kw)
    monkeypatch.setattr(server, "api", flaky)
    try:
        tools.set_name(caller("coder"), name="Rowan")
        raise AssertionError("expected the first naming to fail")
    except server.ServerError:
        pass
    assert server.owner_handle() == "owner" and server.naming_pending() == "rowan"
    out = tools.set_name(caller("coder"), name="Rowan")
    assert out["handle"] == "rowan"  # adopted, not a second @rowan-2 beside an orphan
    m = members()
    assert "rowan-2" not in m and m["owner"]["disabled_at"] and not m["rowan"]["disabled_at"]
    assert server.naming_pending() == "" and server.health()["password_set"] is True


def test_naming_finishes_on_a_retry_after_failing_after_the_switch(hermes_cloud, monkeypatch):
    real = server.run_cli
    calls = {"n": 0}

    def flaky(tok, args, **kw):
        if args[:2] == ["member", "rename"] and not calls["n"]:
            calls["n"] += 1
            return type("R", (), {"returncode": 1, "stderr": "boom", "stdout": ""})()
        return real(tok, args, **kw)
    monkeypatch.setattr(server, "run_cli", flaky)
    try:
        tools.set_name(caller("coder"), name="Rowan")
        raise AssertionError("expected the first naming to fail")
    except server.ServerError:
        pass
    assert server.owner_handle() == "rowan" and not members()["owner"]["disabled_at"]
    tools.set_name(caller("coder"), name="Rowan")
    m = members()
    assert m["owner"]["disabled_at"] and m["owner"]["name"] == "Rowan"


def test_a_profile_cloned_later_is_told_too(hermes_cloud):
    import shutil

    from conftest import make_profile
    accounts.reconcile()
    tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    make_profile(hermes_cloud, "late", annotary=False)
    late = hermes_cloud / "profiles" / "late"
    (late / "config.yaml").write_text("model: test\nplugins:\n  enabled:\n    - annotary\n  disabled: []\n")
    shutil.copytree(hermes_cloud / "plugins" / "annotary", late / "plugins" / "annotary")
    (late / "plugins" / "annotary" / "__init__.py").write_text("# an older version\n")
    accounts.reconcile()
    steps = tools.share(caller("coder"), markdown="# B\n", name="B").get("setup_first", [])
    assert tools.PROFILES_SETUP.format(profiles="late") in steps


def test_a_share_survives_its_setup_steps_failing(hermes_cloud, monkeypatch):
    def broken(*a, **k):
        raise OSError("state unreadable")
    monkeypatch.setattr(tools, "_setup_steps", broken)
    out = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    assert out["id"] and "setup_first" not in out


def test_reconcile_waits_while_the_owner_is_being_switched(hermes_cloud):
    import threading

    done = threading.Event()
    with state.locked("owner"):
        t = threading.Thread(target=lambda: (accounts.reconcile(), done.set()), daemon=True)
        t.start()
        assert not done.wait(0.5)
    t.join(30)
    assert done.is_set()


def _fail_password_once(monkeypatch):
    real, calls = server.api, {"n": 0}

    def flaky(tok, method, path, body=None, **kw):
        if path == "/api/v1/settings/password" and not calls["n"]:
            calls["n"] += 1
            raise server.ServerError("boom")
        return real(tok, method, path, body, **kw)
    monkeypatch.setattr(server, "api", flaky)
    try:
        tools.set_name(caller("coder"), name="Rowan")
        raise AssertionError("expected the first naming to fail")
    except server.ServerError:
        pass
    assert server.naming_pending() == "rowan"


def test_a_retry_under_another_name_drops_the_half_made_member(hermes_cloud, monkeypatch):
    _fail_password_once(monkeypatch)
    out = tools.set_name(caller("coder"), name="Alicia")
    m = members()
    assert out["handle"] == "alicia" and m["alicia"]["name"] == "Alicia"
    assert m["rowan"]["disabled_at"] and m["owner"]["disabled_at"] and server.naming_pending() == ""


def test_a_retry_under_a_variant_of_the_name_adopts_it_and_takes_the_new_spelling(hermes_cloud, monkeypatch):
    _fail_password_once(monkeypatch)
    out = tools.set_name(caller("coder"), name="ROWAN")
    assert out["handle"] == "rowan" and members()["rowan"]["name"] == "ROWAN"


def test_a_retry_that_keeps_the_handle_drops_the_half_made_member(hermes_cloud, monkeypatch):
    _fail_password_once(monkeypatch)
    out = tools.set_name(caller("coder"), name="王伟")
    m = members()
    assert out["handle"] == "owner" and m["rowan"]["disabled_at"] and not m["owner"]["disabled_at"]
    assert server.naming_pending() == "" and server.owner_named()


def test_an_install_that_had_the_old_wake_hint_is_still_asked(hermes_cloud):
    state.update(lambda st: st["hinted"].update({"coder": True}))  # what an earlier build wrote
    assert tools.WAKE_SETUP in tools.share(caller("coder"), markdown="# Plan\n", name="Plan")["setup_first"]


def test_after_naming_old_comments_and_missed_wakeups_name_the_new_handle(hermes_cloud):
    from annotary_hermes import docs
    doc = tools.share(caller("coder"), markdown="# Plan\n\nStep one.\n", name="Plan")["id"]
    r = server.run_cli(server.owner_token(), ["thread", "new", doc, "--document", "-m", "First thought"])
    assert r.returncode == 0, r.stderr
    state.update(lambda st: st["pending"].update({"coder": [{"reason": "mention", "doc": doc, "by": "owner"}]}))
    out = tools.set_name(caller("coder"), name="Rowan")  # every tool hands over missed wake-ups
    assert out["missed_wakeups"][0]["by"] == "rowan"
    assert docs.read_threads(server.owner_token(), doc)[0]["author"] == "rowan"


def test_a_per_profile_install_of_the_same_plugin_is_on_not_a_stale_copy(hermes_cloud):
    import shutil

    from annotary_hermes import enablement
    here = hermes_cloud / "profiles" / "bencha" / "plugins" / "annotary"
    here.unlink()
    shutil.copytree(hermes_cloud / "plugins" / "annotary", here)  # Hermes's "Install here"
    assert enablement.plugin_state("bencha") == enablement.ON
    (here / "plugin.yaml").write_text((here / "plugin.yaml").read_text() + "# changed\n")
    assert enablement.plugin_state("bencha") == enablement.COPY


class FakeTurn:
    """Stands in for the `hermes chat` child: finishes when `release` is set."""

    def __init__(self, code=0):
        import threading
        self.release, self.returncode, self.code = threading.Event(), None, code

    def poll(self):
        return self.returncode

    def communicate(self):
        self.release.wait(10)
        self.returncode = self.code
        return b"", b"boom" if self.code else b""


def _wake_with(inject_ok, consent, bot_chat_ok=True, seq=7):
    from annotary_hermes import rules, watcher
    calls = []

    def bot_chat(profile, text, root=None, *, on_fail=None):
        calls.append((profile, text, on_fail))
        return bot_chat_ok
    w = watcher.Watcher("bencha", lambda text, key: inject_ok, allowed=consent, bot_chat=bot_chat)
    rec = w.deliver(rules.Wake(profile="bencha", reason="mention", doc="d1", name="Plan", by="rowan",
                               thread="t1", excerpt="@bencha hi", seq=seq))
    return rec, calls


def test_a_bot_with_no_live_chat_is_woken_in_its_bot_chat_only_with_consent(hermes_cloud):
    rec, calls = _wake_with(inject_ok=False, consent=lambda: True)
    assert rec["outcome"] == "woke" and len(calls) == 1 and calls[0][0] == "bencha"
    assert not state.load()["pending"].get("bencha")
    calls[0][2]()  # the turn failed later: the wake is kept for the Bot after all
    assert state.load()["pending"]["bencha"][-1]["seq"] == 7
    state.update(lambda st: st["pending"].pop("bencha"))
    rec, calls = _wake_with(inject_ok=False, consent=lambda: False, seq=8)
    assert rec["outcome"] == "notified" and calls == []
    assert state.load()["pending"]["bencha"][-1]["seq"] == 8


def test_a_live_chat_or_unknown_consent_never_reaches_the_bot_chat(hermes_cloud):
    def unknown():
        raise AttributeError("an older Hermes")
    assert _wake_with(inject_ok=True, consent=lambda: True)[1] == []
    rec, calls = _wake_with(inject_ok=False, consent=unknown, seq=8)
    assert rec["outcome"] == "notified" and calls == []


def test_a_bot_chat_turn_runs_one_at_a_time_and_a_failed_one_becomes_a_notification(hermes_cloud):
    from annotary_hermes import watcher
    turns, failed = [], []

    def spawn(argv, **kw):
        assert kw["start_new_session"] is True and kw["stdin"] is not None
        turns.append((argv, FakeTurn(code=1)))
        return turns[-1][1]
    assert watcher.wake_bot_chat("bencha", "[Annotary] first", spawn=spawn, on_fail=lambda: failed.append(1))
    argv, turn = turns[0]
    i = argv.index("-p")
    assert argv[i:i + 3] == ["-p", "bencha", "chat"] and argv[argv.index("-c") + 1] == "Bot Chat"
    assert "--create-if-missing" in argv and "-Q" in argv
    query = Path(argv[argv.index("--query-file") + 1])
    assert query.read_text(encoding="utf-8") == "[Annotary] first"
    assert not watcher.wake_bot_chat("bencha", "[Annotary] second", spawn=spawn)  # busy: stays a notification
    assert len(turns) == 1
    turn.release.set()
    for _ in range(100):
        if failed:
            break
        import time
        time.sleep(0.02)
    assert failed == [1] and not query.exists()
    assert watcher.wake_bot_chat("bencha", "[Annotary] third", spawn=spawn)  # free again
    turns[-1][1].release.set()


def test_a_sole_install_outside_default_is_on(hermes_cloud, monkeypatch):
    import shutil

    from annotary_hermes import enablement, paths
    here = hermes_cloud / "profiles" / "bencha" / "plugins" / "annotary"
    here.unlink()
    shutil.copytree(hermes_cloud / "plugins" / "annotary", here)
    shutil.rmtree(hermes_cloud / "plugins" / "annotary")  # nothing in default
    monkeypatch.setattr(paths, "package_dir", lambda: here)
    assert enablement.plugin_state("bencha") == enablement.ON


def test_a_bot_chat_turn_that_ends_unknown_becomes_a_notification(hermes_cloud):
    from annotary_hermes import watcher
    failed = []

    class Broken(FakeTurn):
        def communicate(self):
            raise OSError("pipe gone")
    assert watcher.wake_bot_chat("coder", "[Annotary] x", spawn=lambda argv, **kw: Broken(),
                                 on_fail=lambda: failed.append(1))
    import time
    for _ in range(100):
        if failed:
            break
        time.sleep(0.02)
    assert failed == [1]


# Approval markers; Hermes's gateway_chat._ENV_LAUNCH_FLAGS (YOLO plus the next four after the markers)
# become a new session's policy; session_client_env.BEHAVIOUR_ENV (the last four) its frozen client_env.
STRIPPED = ("HERMES_YOLO_MODE", "HERMES_CRON_SESSION", "HERMES_EXEC_ASK", "HERMES_GATEWAY_SESSION",
            "HERMES_ACCEPT_HOOKS", "HERMES_IGNORE_RULES", "HERMES_SAFE_MODE", "HERMES_IGNORE_USER_CONFIG",
            "HERMES_EPHEMERAL_SYSTEM_PROMPT", "HERMES_PREFILL_MESSAGES_FILE", "HERMES_INFERENCE_PROVIDER",
            "HERMES_ENABLE_PROJECT_PLUGINS")


def test_a_bot_chat_turn_never_inherits_yolo_or_the_gateways_approval_context(hermes_cloud, monkeypatch):
    from annotary_hermes import watcher
    for name in STRIPPED + ("HERMES_SESSION_KEY", "HERMES_SESSION_PLATFORM"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("HERMES_HOME", str(hermes_cloud))
    seen = []

    def spawn(argv, **kw):
        seen.append(kw.get("env"))
        turn = FakeTurn(code=0)
        turn.release.set()
        return turn
    assert watcher.wake_bot_chat("bencha", "[Annotary] x", spawn=spawn)
    env = seen[0]
    assert env is not None, "the child must get an explicit env, not the gateway's"
    assert not [k for k in env if k in STRIPPED or k.startswith("HERMES_SESSION_")]
    assert env["HERMES_HOME"] == str(hermes_cloud)  # everything else still passes through
