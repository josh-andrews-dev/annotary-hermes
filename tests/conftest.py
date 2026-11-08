"""Fixtures: a throwaway Hermes root with profiles, and a real private Annotary server in it.

The server is the pinned release binary (downloaded once into a cache and checked against the
pinned SHA-256), or ANNOTARY_HERMES_DEV_BINARY when set. Nothing here touches a real Hermes or
~/.annotary.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))  # tests import make_profile from here

from annotary_hermes import install, server  # noqa: E402

CACHE = Path(os.environ.get("ANNOTARY_HERMES_TEST_CACHE", Path.home() / ".cache" / "annotary-hermes-tests"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_profile(root: Path, name: str, profile_yaml: str = "") -> Path:
    home = root if name == "default" else root / "profiles" / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("model: test\n")
    if profile_yaml:
        (home / "profile.yaml").write_text(profile_yaml)
    return home


@pytest.fixture()
def hermes(tmp_path, monkeypatch):
    """A Hermes root (default + coder + bencha) with its private server running."""
    root = tmp_path / "hermes"
    for name in ("default", "coder", "bencha"):
        make_profile(root, name)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("ANNOTARY_HERMES_PORT", str(_free_port()))
    monkeypatch.setenv(install.DOWNLOAD_CACHE_ENV, str(CACHE))
    for k in list(os.environ):
        if k.startswith("ANNOTARY_") and k not in ("ANNOTARY_HERMES_PORT", "ANNOTARY_HERMES_DEV_BINARY",
                                                   "ANNOTARY_HERMES_DOWNLOAD_CACHE"):
            monkeypatch.delenv(k)
    if not os.environ.get(install.DEV_BINARY_ENV):
        install.install_binary(cache_dir=CACHE)
    server.ensure_running()
    yield root
    server.stop()
