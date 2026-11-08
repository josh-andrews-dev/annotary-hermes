"""Handle and display-name mapping (D3) and reading profile.yaml."""

from conftest import make_profile

from annotary_hermes import accounts


def P(pid, **kw):
    return accounts.Profile(id=pid, home=None, **kw)


def test_named_profile_handle_is_its_name():
    assert accounts.desired_handle(P("coder"), "josh") == "coder"
    assert accounts.desired_handle(P("Research_Bot"), "josh") == "research-bot"


def test_default_profile_is_hermes_until_named():
    assert accounts.desired_handle(P("default"), "josh") == "hermes"
    assert accounts.desired_handle(P("default", display_name="Maia"), "josh") == "maia"
    assert accounts.desired_handle(P("default", bot_title="Big Helper"), "josh") == "big-helper"


def test_clash_with_the_person_gets_agent_suffix():
    assert accounts.desired_handle(P("josh"), "josh") == "josh-agent"


def test_display_name_prefers_bot_title():
    assert accounts.display_name(P("coder", bot_title="Coder Bot", display_name="C")) == "Coder Bot"
    assert accounts.display_name(P("coder", display_name="C")) == "C"
    assert accounts.display_name(P("coder")) == "coder"
    assert accounts.display_name(P("default")) == "Hermes"


def test_profile_yaml_fields(tmp_path):
    home = make_profile(tmp_path, "default", (
        "description: x\ndisplay_name: Maia\nprevious_names:\n  - old\n  - older\n"
        "ui_meta:\n  hermes-bots:\n    title: Maia the Bot\n"))
    p = accounts.read_profile("default", home)
    assert (p.display_name, p.bot_title, p.previous_names) == ("Maia", "Maia the Bot", ["old", "older"])


def test_list_profiles_skips_folders_without_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    make_profile(tmp_path, "default")
    make_profile(tmp_path, "coder")
    (tmp_path / "profiles" / "junk").mkdir()
    assert [p.id for p in accounts.list_profiles(tmp_path)] == ["default", "coder"]
