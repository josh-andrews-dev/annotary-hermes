"""Where Annotary for Hermes keeps its files.

Everything shared by the whole Hermes install lives under the Hermes root (the default profile's
home), so every profile finds the same private server:

    <root>/annotary/bin/annotary        the pinned binary (SHA-256 checked)
    <root>/annotary/data/               ANNOTARY_HOME of the private server (never ~/.annotary)
    <root>/annotary/secrets.json  0600  owner password and owner Token
    <root>/annotary/state.json          Members per profile, Document editors, wake bookkeeping
    <root>/desktop-plugins/annotary/    the desktop page, a standalone desktop plugin (no marker)
    <profile home>/plugin-data/annotary/token  0600  that profile's Member Token
"""

from __future__ import annotations

import os
from pathlib import Path

PLUGIN_ID = "annotary"
#: The private server's fixed loopback port. Not 7377, so a standalone Annotary keeps its own.
DEFAULT_PORT = 7391


def hermes_root() -> Path:
    """The Hermes root (the default profile's home), whichever profile this process runs as."""
    try:
        from hermes_constants import get_default_hermes_root
    except ImportError:  # outside Hermes (the tests): HERMES_HOME names the root
        return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    return Path(get_default_hermes_root())


def current_home() -> Path:
    """The Hermes home of the profile this call runs for (per turn inside the gateway)."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    return Path(get_hermes_home())


def profile_home(profile: str, root: Path | None = None) -> Path:
    root = root or hermes_root()
    return root if profile == "default" else root / "profiles" / profile


def profile_of_home(home: Path, root: Path | None = None) -> str:
    root = (root or hermes_root()).resolve()
    home = Path(home).resolve()
    if home == root:
        return "default"
    if home.parent == root / "profiles":
        return home.name
    return "custom"


def app_dir(root: Path | None = None) -> Path:
    d = (root or hermes_root()) / "annotary"
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir(root: Path | None = None) -> Path:
    return app_dir(root) / "data"


def port() -> int:
    """The server port. ``ANNOTARY_HERMES_PORT`` is for tests and development only."""
    value = os.environ.get("ANNOTARY_HERMES_PORT", "")
    return int(value) if value.isdigit() else DEFAULT_PORT


def server_url() -> str:
    return f"http://127.0.0.1:{port()}"


def token_path(profile: str, root: Path | None = None) -> Path:
    return profile_home(profile, root) / "plugin-data" / PLUGIN_ID / "token"


def shares_dir(profile: str, root: Path | None = None) -> Path:
    """Where a Markdown body handed to ``annotary_share`` is written before it is pushed."""
    return profile_home(profile, root) / "plugin-data" / PLUGIN_ID / "shares"


def desktop_page_target(root: Path | None = None) -> Path:
    return (root or hermes_root()) / "desktop-plugins" / PLUGIN_ID


def package_dir() -> Path:
    """The installed plugin package (this file's parent's parent)."""
    return Path(__file__).resolve().parent.parent


def write_secret(path: Path, data: str) -> None:
    """Write *data* to *path* with mode 600, replacing it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
