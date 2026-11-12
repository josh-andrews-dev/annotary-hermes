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

    def answer(stdout, code=0):
        def run(args, timeout=180):
            seen.append((args, timeout))
            return subprocess.CompletedProcess(args, code, stdout, "")
        return run
    monkeypatch.setattr(cli, "_run_hermes", answer("true\n"))
    assert cli.wake_allowed("bencha") is True
    args, timeout = seen[-1]
    assert args[:2] == ["-p", "bencha"] and "--json" in args
    assert args[-1] == "plugins.entries.annotary.allow_gateway_injection"
    assert timeout == cli.WAKE_ALLOWED_TIMEOUT < 180  # a stuck `hermes` must not hold the watcher
    # Hermes's own check takes only the boolean: a quoted 'true' in config.yaml is no.
    for stdout, code in [("false\n", 0), ('"true"\n', 0), ("true\n", 1), ("", 1), ("not json", 0)]:
        monkeypatch.setattr(cli, "_run_hermes", answer(stdout, code))
        assert cli.wake_allowed("bencha") is False, (stdout, code)

    def boom(args, timeout=180):
        raise subprocess.TimeoutExpired(args, timeout)
    monkeypatch.setattr(cli, "_run_hermes", boom)
    assert cli.wake_allowed("bencha") is False
