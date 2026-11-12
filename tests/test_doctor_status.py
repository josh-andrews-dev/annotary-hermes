"""What `doctor` says about the Webapp, and what `status` says a wake-up means."""

import importlib.util
import json
import shutil
import subprocess
import sys
import time
import types

import pytest
from conftest import ROOT

from annotary_hermes import cli, desktop, paths, state

ADVICE = "Where Web Access cannot be switched on"


@pytest.fixture()
def webapp(hermes, monkeypatch):
    """Set what `hermes webapp --status` prints and what config.yaml says."""
    def configure(status, config=""):
        monkeypatch.setattr(cli, "_run_hermes", lambda args: subprocess.CompletedProcess(args, 0, status, ""))
        if config:
            with (hermes / "config.yaml").open("a") as f:
                f.write(config)
    return configure


def doctor_output(capsys):
    cli.doctor()
    return capsys.readouterr().out


def test_no_setup_advice_while_the_webapp_is_serving(webapp, capsys):
    webapp("Serving at http://127.0.0.1:9120")
    out = doctor_output(capsys)
    assert "Serving at http://127.0.0.1:9120" in out and ADVICE not in out


def test_no_setup_advice_when_the_config_turns_it_on_and_the_gateway_is_still_starting(webapp, capsys):
    webapp("The gateway is still starting the Webapp.", "webapp:\n  enabled: true\n")
    assert ADVICE not in doctor_output(capsys)


def test_the_setup_advice_shows_when_the_webapp_is_not_set_up(webapp, capsys):
    webapp("The Webapp is not enabled.")
    out = doctor_output(capsys)
    assert ADVICE in out and "public_url: https://<the HTTPS address you serve it at>" in out


def test_a_configured_public_address_is_where_annotary_links_open(webapp, capsys):
    webapp("Serving at http://[::1]:9120", "webapp:\n  enabled: true\n  public_url: https://agent.example.test/\n")
    out = doctor_output(capsys)
    assert ADVICE not in out and "https://agent.example.test/?annotary=<id>." in out


def test_a_public_address_on_a_webapp_that_is_off_is_not_advertised(webapp, capsys):
    webapp("The Webapp is not enabled.", "webapp:\n  enabled: false\n  public_url: https://agent.example.test\n")
    out = doctor_output(capsys)
    assert ADVICE in out and "agent.example.test" not in out


@pytest.mark.parametrize("bad", ["example.test", "9120", "ftp://agent.example.test", "https://user@agent.example.test"])
def test_a_public_address_hermes_would_reject_is_not_advertised(webapp, capsys, bad):
    webapp("Serving at http://[::1]:9120", f"webapp:\n  enabled: true\n  public_url: {bad}\n")
    out = doctor_output(capsys)
    assert bad not in out.replace("[::1]:9120", "") and ADVICE not in out


def test_enabled_must_be_true_not_merely_present(webapp, capsys):
    webapp("The Webapp is not enabled.", "webapp:\n  enabled: 'false'\n")
    assert ADVICE in doctor_output(capsys)


def _hermes_config(monkeypatch, conf):
    """Run as Hermes does: its public `load_config_readonly`, the merged config of this home."""
    mod = types.ModuleType("hermes_cli.config")
    mod.load_config_readonly = lambda: conf
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)


def test_inside_hermes_the_merged_config_wins_over_the_file(webapp, capsys, monkeypatch):
    """Hermes Cloud's address can come from the managed overlay or `${ENV}`, never in the file."""
    webapp("The gateway is still starting the Webapp.", "webapp:\n  enabled: false\n")
    _hermes_config(monkeypatch, {"webapp": {"enabled": True, "public_url": "https://hermes.example.test/"}})
    out = doctor_output(capsys)
    assert ADVICE not in out and "https://hermes.example.test/?annotary=<id>." in out


def test_the_merged_config_is_held_to_the_same_rules(webapp, capsys, monkeypatch):
    webapp("The Webapp is not enabled.")
    _hermes_config(monkeypatch, {"webapp": {"enabled": True, "port": 0, "public_url": "https://hermes.example.test"}})
    assert ADVICE in doctor_output(capsys)


def test_no_internal_hermes_module_is_imported():
    """Catalog rule: only Hermes's public reads, so a core release cannot break the plugin."""
    for f in [ROOT / "__init__.py", *sorted((ROOT / "annotary_hermes").glob("*.py"))]:
        text = f.read_text()
        assert "gateway.webapp_listener" not in text and "_gateway_injection_allowed" not in text, f.name


def _dashboard(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api


def _page_folder(js: str, marker: bool):
    target = paths.desktop_page_target()
    target.mkdir(parents=True, exist_ok=True)
    (target / "plugin.js").write_text(js)
    if marker:
        (target / desktop.MARKER).write_text(json.dumps(  # the shape Hermes's reconcile writes
            {"package": "annotary", "source": "/hermes/plugins/annotary/desktop", "sourceMtimeMs": 1}))
    return target


def test_an_earlier_versions_standalone_page_is_removed_from_the_page_status_call(hermes):
    """Hermes never publishes the package's half over a marker-less folder, so the old copy goes."""
    target = _page_folder("const ID = 'annotary'\n// an earlier version's hand-copied page\n", marker=False)
    assert desktop.page_status()["standalone_copy"]
    _dashboard("annotary_dashboard_page_retire")._status()
    assert not target.exists()


def test_the_published_half_and_other_folders_are_left_alone(hermes):
    api = _dashboard("annotary_dashboard_page_keep")
    target = _page_folder("const ID = 'annotary'\n", marker=True)
    api._status()
    assert (target / "plugin.js").is_file() and desktop.page_status()["paired"]
    shutil.rmtree(target)
    foreign = "// someone else's plugin in this folder\n"
    target = _page_folder(foreign, marker=False)
    api._status()
    assert (target / "plugin.js").read_text() == foreign
    shutil.rmtree(target)
    edited = "const ID = 'annotary'\n// a page kept and edited by hand\n"
    target = _page_folder(edited, marker=False)
    (target / "notes.md").write_text("mine\n")
    api._status()
    assert (target / "plugin.js").read_text() == edited and (target / "notes.md").is_file()


def test_an_invalid_marker_does_not_count_as_paired(hermes):
    """Hermes ignores a marker without package and source, and so must the status and cleanup."""
    target = _page_folder("const ID = 'annotary'\n", marker=False)
    (target / desktop.MARKER).write_text('{"packageName": "annotary"}')
    assert not desktop.page_status()["paired"]
    assert desktop.retire_standalone_page() and not target.exists()


def test_a_copy_equal_to_the_half_is_left_for_hermes_to_adopt(hermes):
    target = _page_folder(desktop.source().read_text(), marker=False)
    assert not desktop.retire_standalone_page() and (target / "plugin.js").is_file()


def test_a_copy_that_cannot_be_removed_is_reported_not_raised(hermes, monkeypatch):
    target = _page_folder("const ID = 'annotary'\n", marker=False)
    def refuse(*_a, **_k):
        raise PermissionError("locked")
    monkeypatch.setattr(desktop.shutil, "rmtree", refuse)
    assert desktop.retire_standalone_page() is False and target.exists()


def test_a_page_that_cannot_be_removed_does_not_stop_the_status_call(hermes, monkeypatch, caplog):
    api = _dashboard("annotary_dashboard_page_err")
    def refuse(*_a, **_k):
        raise OSError("read-only")
    monkeypatch.setattr(desktop, "retire_standalone_page", refuse)
    assert api._status()["ok"] is True
    assert "could not remove the old standalone desktop page" in caplog.text


def test_status_does_not_claim_a_turn_ran(hermes, capsys):
    state.update(lambda s: s.setdefault("wake_log", []).extend([
        {"at": time.time(), "profile": "coder", "outcome": "woke"},
        {"at": time.time(), "profile": "coder", "outcome": "notified"},
        {"at": time.time(), "profile": "coder", "outcome": "capped"}]))
    cli.status()
    wakes = json.loads(capsys.readouterr().out)["recent_wakes"]
    assert [w["outcome"] for w in wakes] == ["woke", "notified", "capped"]  # stored values stay stable
    assert "handed to Hermes" in wakes[0]["result"] and "not show a turn ran" in wakes[0]["result"]
    assert "notification" in wakes[1]["result"] and "Dropped" in wakes[2]["result"]
