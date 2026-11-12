"""What the Hermes plugin catalog's review asked of the plugin: a minimal environment for the
bundled binary, and consent read per profile through a public Hermes command."""

import subprocess

from annotary_hermes import cli, server


def test_the_binary_never_inherits_the_hosts_environment(hermes, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-annotary")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-for-annotary")
    monkeypatch.setenv("HERMES_SESSION_KEY", "agent:main")
    monkeypatch.setenv("ANNOTARY_TOKEN", "a-standalone-token")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("TZ", "UTC")
    env = server.cli_env("the-plugins-token")
    assert set(env) <= {"PATH", "HOME", "LANG", "TMPDIR", "TZ", "LC_ALL", "NO_COLOR", "ANNOTARY_HOME",
                        "ANNOTARY_SERVER", "ANNOTARY_UPDATE_CHECK", "ANNOTARY_TOKEN"}
    assert env["ANNOTARY_TOKEN"] == "the-plugins-token" and env["LC_ALL"] == "C.UTF-8" and env["TZ"] == "UTC"
    assert "ANNOTARY_TOKEN" not in server.cli_env(None)


def test_consent_is_read_for_the_named_profile_and_fails_closed(monkeypatch):
    seen = []

    def run(args, answer="true\n", code=0):
        seen.append(args)
        return subprocess.CompletedProcess(args, code, answer, "")
    monkeypatch.setattr(cli, "_run_hermes", run)
    assert cli.wake_allowed("bencha") is True
    assert seen[-1][:2] == ["-p", "bencha"] and seen[-1][-1] == "plugins.entries.annotary.allow_gateway_injection"
    monkeypatch.setattr(cli, "_run_hermes", lambda args: run(args, "false\n"))
    assert cli.wake_allowed("bencha") is False
    monkeypatch.setattr(cli, "_run_hermes", lambda args: run(args, "true\n", 1))
    assert cli.wake_allowed("bencha") is False

    def boom(args):
        raise subprocess.TimeoutExpired(args, 180)
    monkeypatch.setattr(cli, "_run_hermes", boom)
    assert cli.wake_allowed("bencha") is False
