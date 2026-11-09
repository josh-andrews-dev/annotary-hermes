"""What `doctor` says about the Webapp, and what `status` says a wake-up means."""

import json
import subprocess
import time

import pytest

from annotary_hermes import cli, state

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
    assert ADVICE not in out and "https://agent.example.test/#/annotary?doc=<id>" in out


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
