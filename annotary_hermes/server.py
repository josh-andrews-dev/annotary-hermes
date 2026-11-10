"""The private Annotary server: first-run setup, ensure-running, stop, and how to call it.

One server per Hermes install, on loopback, its data dir under the Hermes root. It runs detached
(its own session), so it outlives gateway restarts and serves CLI-only use; an flock makes sure
only one caller at a time checks and starts it, and Annotary's own LOCK refuses a second copy.
Secrets (owner password, Tokens) are never printed, logged or put on a command line.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import install, paths, state

SETUP_TIMEOUT = 60


class ServerError(RuntimeError):
    pass


def secrets_file(root: Path | None = None) -> Path:
    return paths.app_dir(root) / "secrets.json"


def _secrets(root: Path | None = None) -> dict:
    try:
        return json.loads(secrets_file(root).read_text())
    except (OSError, ValueError):
        return {}


def owner_token(root: Path | None = None) -> str:
    tok = _secrets(root).get("owner_token", "")
    if not tok:
        raise ServerError("the private Annotary server is not set up yet")
    return tok


def owner_handle(root: Path | None = None) -> str:
    return _secrets(root).get("owner_handle", "")


def cli_env(token: str | None = None, root: Path | None = None) -> dict:
    """The environment for the bundled CLI and server: our data dir and server, never ~/.annotary,
    no update check (nothing leaves the machine), and the Token in the environment only."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANNOTARY_")}
    env["ANNOTARY_HOME"] = str(paths.data_dir(root))
    env["ANNOTARY_SERVER"] = paths.server_url()
    env["ANNOTARY_UPDATE_CHECK"] = "off"
    env["NO_COLOR"] = "1"
    if token:
        env["ANNOTARY_TOKEN"] = token
    return env


def run_cli(token: str, args: list[str], *, cwd: str | Path | None = None, stdin: str | None = None,
            timeout: float = 60, root: Path | None = None) -> subprocess.CompletedProcess:
    """Run the bundled CLI: argv only, no shell, the Token in the environment."""
    return subprocess.run(
        [str(install.bin_path(root)), *args], env=cli_env(token, root), cwd=str(cwd) if cwd else None,
        input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout)


def api(token: str, method: str, path: str, body: dict | None = None, *, timeout: float = 30) -> dict:
    """Call the private server's JSON API. Raises ServerError with the server's message."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(paths.server_url() + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}")
        except ValueError:
            detail = {}
        err = ServerError(detail.get("message") or f"HTTP {e.code}")
        err.status = e.code  # type: ignore[attr-defined]
        err.detail = detail  # type: ignore[attr-defined]
        raise err from None
    except (urllib.error.URLError, OSError) as e:
        raise ServerError(f"the private Annotary server is unreachable ({e})") from None
    return json.loads(raw) if raw else {}


def health(timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(paths.server_url() + "/api/v1/health", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 — any failure means "not answering"
        return None


def slug(text: str, *, max_len: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].strip("-")


def _os_identity() -> tuple[str, str]:
    user = getpass.getuser()
    name = user
    try:
        import pwd
        gecos = pwd.getpwnam(user).pw_gecos.split(",")[0].strip()
        name = gecos or user
    except (ImportError, KeyError):
        pass
    return slug(user) or "owner", name


def parse_setup_token(stdout: str) -> str | None:
    """The owner Token from ``serve --setup-only --json``, which prints one JSON object
    (``{"created":true,"handle":…,"token":…,"store":…}``). The one place that reads setup output."""
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                tok = json.loads(line).get("token")
            except ValueError:
                tok = None
            if tok:
                return tok
    return None


def setup_if_needed(root: Path | None = None) -> bool:
    """First-run setup with no prompts: the owner Member from the OS user and a long random
    password nobody types (it closes loopback trust). Returns True when it ran."""
    if _secrets(root).get("owner_token"):
        return False
    handle, name = _os_identity()
    password = secrets.token_urlsafe(32)
    env = cli_env(None, root)
    env.update(ANNOTARY_SETUP_HANDLE=handle, ANNOTARY_SETUP_NAME=name, ANNOTARY_SETUP_PASSWORD=password)
    paths.data_dir(root).mkdir(parents=True, exist_ok=True)
    out = subprocess.run(
        [str(install.bin_path(root)), "serve", "--setup-only", "--json", "--data-dir", str(paths.data_dir(root)),
         "--port", str(paths.port())],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=SETUP_TIMEOUT)
    token = parse_setup_token(out.stdout)
    if out.returncode != 0 or not token:
        # Never echo stdout: it holds the Token. Only the error stream's tail, which does not.
        raise ServerError(f"first-run setup failed (exit {out.returncode}): {out.stderr.strip()[-300:]}")
    paths.write_secret(secrets_file(root), json.dumps(
        {"owner_handle": handle, "owner_password": password, "owner_token": token}))
    return True


def _pid_file(root: Path | None = None) -> Path:
    return paths.app_dir(root) / "server.pid"


def log_file(root: Path | None = None) -> Path:
    d = paths.data_dir(root) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "hermes-serve.log"


def _current(h: dict | None, root: Path | None) -> bool:
    """The server answers, is set up for this plugin, and runs the binary this plugin pins (or
    the dev override, whatever its version)."""
    if not (h and h.get("ok") and _secrets(root).get("owner_token")):
        return False
    if not install.installed(root)["ok"]:
        return False
    if install.dev_binary():
        return True
    return h.get("version") == install.VERSION.lstrip("v") and _runs_pinned_binary(root)


def _runs_pinned_binary(root: Path | None) -> bool:
    """Whether our server process was started from the pinned binary: a dev build can report the
    pinned version. Read from the process itself, so it holds whoever started it."""
    pid = server_pid(root)
    out = _command(pid) if pid else ""
    if not _serves_our_data(out, root):
        return True  # no process of ours to compare; the version already matched
    return out.startswith(f"{install.bin_path(root)} serve ")


def ensure_running(root: Path | None = None) -> dict:
    """Health check; else install, set up and start the server detached. A running server on a
    missing or stale binary (a new pin after a plugin upgrade) gets the pinned one and a restart.
    Safe to call from every entry point (tools, backend routes, the gateway, `hermes annotary`)."""
    h = health(1.0)
    if _current(h, root):
        return {"outcome": "running", "health": h}
    with state.locked("ensure", root):
        h = health(1.0)
        if _current(h, root):
            return {"outcome": "running", "health": h}
        install.install_binary(root)
        if h and h.get("ok"):
            if not _secrets(root).get("owner_token"):
                raise ServerError(f"another server answers on port {paths.port()} but this plugin has no "
                                  "Token for it; run `hermes annotary doctor`")
            if not stop(root)["stopped"]:
                raise ServerError(f"the server on port {paths.port()} runs an old binary and could not be "
                                  "stopped; run `hermes annotary stop`, then try again")
        setup_if_needed(root)
        from . import desktop  # an earlier version's hand-copied page would block the package's half
        desktop.retire_standalone_page(root)
        log = open(log_file(root), "a")
        proc = subprocess.Popen(
            [str(install.bin_path(root)), "serve", "--data-dir", str(paths.data_dir(root)),
             "--port", str(paths.port()), "--bind", "127.0.0.1"],
            env=cli_env(None, root), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True, close_fds=True, cwd=str(paths.data_dir(root)))
        log.close()
        _pid_file(root).write_text(str(proc.pid))
        for _ in range(150):
            h = health(0.5)
            if h and h.get("ok"):
                return {"outcome": "started", "pid": proc.pid, "health": h}
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        raise ServerError(f"the server did not start (exit {proc.poll()}); see `hermes annotary logs`")


def server_pid(root: Path | None = None) -> int | None:
    try:
        info = json.loads((paths.data_dir(root) / "server.json").read_text())
        pid = int(info.get("pid") or 0)
    except (OSError, ValueError):
        try:
            pid = int(_pid_file(root).read_text().strip())
        except (OSError, ValueError):
            return None
    return pid or None


def _command(pid: int) -> str:
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _serves_our_data(command: str, root: Path | None) -> bool:
    # Ours when it serves our data dir, whichever binary runs it (the pinned one or a dev build).
    return ("annotary" in command and " serve " in f" {command} "
            and f"--data-dir {paths.data_dir(root)} " in f"{command} ")


def _is_our_server(pid: int, root: Path | None = None) -> bool:
    return _serves_our_data(_command(pid), root)


def stop(root: Path | None = None) -> dict:
    pid = server_pid(root)
    if not pid or not _is_our_server(pid, root):
        return {"stopped": False, "reason": "not running"}
    os.kill(pid, 15)
    for _ in range(50):
        if not _is_our_server(pid, root):
            break
        time.sleep(0.1)
    _pid_file(root).unlink(missing_ok=True)
    return {"stopped": True, "pid": pid}
