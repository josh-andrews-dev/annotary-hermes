"""The person's own name: a placeholder on a service account, the first-share setup steps, and
annotary_set_name, against a real private `annotary serve`."""

import json

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


def test_a_named_os_user_is_the_person_and_is_never_asked(hermes):
    assert server.owner_named()
    out = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    assert not any("annotary_set_name" in s for s in out.get("setup_first", []))


def test_the_first_share_leads_with_setup_and_asks_the_name_once(hermes_cloud):
    first = tools.share(caller("coder"), markdown="# Plan\n", name="Plan")
    assert first["setup_first"] == [tools.PAGE_SETUP, tools.NAME_SETUP.format(handle="owner")]
    assert "Start your reply" in first["setup_how"]
    again = tools.share(caller("coder"), markdown="# Other\n", name="Other")
    assert again["setup_first"] == [tools.PAGE_SETUP]  # the page step stays until the page loads
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
    assert steps == [tools.PAGE_SETUP]  # named now: no profile asks again


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
