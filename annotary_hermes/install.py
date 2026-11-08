"""Download the pinned ``annotary`` binary from Annotary's GitHub Release and check it.

The version and every platform's SHA-256 are pinned here, in the source: a new pin is a reviewed
change, never fetched at run time (catalog rules 3 and 17). The plugin never updates itself.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from . import paths

VERSION = "v0.4.1"
BASE_URL = f"https://github.com/josh-andrews-dev/annotary/releases/download/{VERSION}"
#: (sys.platform, machine) -> (Rust target, SHA-256 of annotary-<target>.tar.gz), from the
#: release's sha256.sum. Each tarball also carries a GitHub build attestation
#: (`gh attestation verify <tarball> --repo josh-andrews-dev/annotary`).
PINS: dict[tuple[str, str], tuple[str, str]] = {
    ("darwin", "arm64"): ("aarch64-apple-darwin",
                          "43bc833174b970bb9329cd691a58e50d050eb9d7c010fa1ab12f4aa0403d60de"),
    ("darwin", "x86_64"): ("x86_64-apple-darwin",
                           "ff590f31b5de29c43bbfc0d5f65e3ced7c2df3dd77aff0c434bcdbec0f59df9b"),
    ("linux", "aarch64"): ("aarch64-unknown-linux-gnu",
                           "1684b7cac6aef5f38d4a0153251bbb5050c6f0ed9d917f758aed0689ea93e0e3"),
    ("linux", "x86_64"): ("x86_64-unknown-linux-gnu",
                          "78da46e5363f095b4f5e7319c95dfa7615e6c03823086bf8406e4ab8c9884965"),
}
#: Development only: run this binary instead of the pinned release (an unreleased Annotary build).
DEV_BINARY_ENV = "ANNOTARY_HERMES_DEV_BINARY"


class InstallError(RuntimeError):
    pass


def platform_pin() -> tuple[str, str]:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "aarch64", "arm64": "arm64"}.get(machine, machine)
    if sys.platform.startswith("linux"):
        key = ("linux", "aarch64" if machine in ("arm64", "aarch64") else machine)
    elif sys.platform == "darwin":
        key = ("darwin", "arm64" if machine in ("arm64", "aarch64") else machine)
    else:
        key = (sys.platform, machine)
    if key not in PINS:
        raise InstallError(f"Annotary ships for macOS and Linux only; this is {key[0]}/{key[1]}")
    return PINS[key]


def bin_dir(root: Path | None = None) -> Path:
    return paths.app_dir(root) / "bin"


#: Development and tests only: keep checked release tarballs here so they download once.
DOWNLOAD_CACHE_ENV = "ANNOTARY_HERMES_DOWNLOAD_CACHE"


def dev_binary() -> str:
    return os.environ.get(DEV_BINARY_ENV, "")


def bin_path(root: Path | None = None) -> Path:
    dev = dev_binary()
    if dev:
        return Path(dev).expanduser()
    return bin_dir(root) / "annotary"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def installed(root: Path | None = None) -> dict:
    """What is installed: the binary, the pin it came from, whether it matches this plugin's pin."""
    if dev_binary():
        p = bin_path(root)
        return {"path": str(p), "dev": True, "ok": p.is_file() and os.access(p, os.X_OK)}
    target, sha = platform_pin()
    p = bin_path(root)
    marker = bin_dir(root) / "SHA256"
    pinned = marker.is_file() and marker.read_text().strip() == sha
    return {"path": str(p), "version": VERSION, "target": target, "ok": p.is_file() and pinned}


def install_binary(root: Path | None = None, cache_dir: Path | None = None) -> dict:
    """Download, check against the pinned SHA-256, unpack. Idempotent. *cache_dir* (tests) keeps
    the checked tarball so a test run downloads it once."""
    state = installed(root)
    if state["ok"]:
        return {**state, "installed": False}
    if state.get("dev"):
        raise InstallError(f"{DEV_BINARY_ENV} names a file that is not an executable")
    target, sha = platform_pin()
    asset = f"annotary-{target}.tar.gz"
    if cache_dir is None and os.environ.get(DOWNLOAD_CACHE_ENV):
        cache_dir = Path(os.environ[DOWNLOAD_CACHE_ENV]).expanduser()
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="annotary-dl-") as tmp:
        tmp_path = Path(tmp)
        tgz = tmp_path / asset
        cached = cache_dir / asset if cache_dir else None
        if cached and cached.is_file() and sha256_file(cached) == sha:
            shutil.copyfile(cached, tgz)
        else:
            req = urllib.request.Request(f"{BASE_URL}/{asset}", headers={"User-Agent": "annotary-hermes"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tgz, "wb") as f:
                shutil.copyfileobj(r, f)
        got = sha256_file(tgz)
        if got != sha:
            raise InstallError(f"checksum mismatch for {asset}: got {got[:12]}…, pinned {sha[:12]}…")
        if cached and not cached.is_file():
            cached.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tgz, cached)
        with tarfile.open(tgz) as tf:
            try:
                member = tf.getmember(f"annotary-{target}/annotary")
            except KeyError as e:
                raise InstallError("the release tarball has no annotary binary") from e
            if not member.isfile():
                raise InstallError("the binary in the release tarball is not a regular file")
            out = tmp_path / "annotary"
            src = tf.extractfile(member)
            assert src is not None
            with open(out, "wb") as f:
                shutil.copyfileobj(src, f)
        os.chmod(out, 0o755)
        dest = bin_path(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(out, dest)
        (bin_dir(root) / "SHA256").write_text(sha + "\n")
    return {**installed(root), "installed": True, "seconds": round(time.time() - t0, 2)}
