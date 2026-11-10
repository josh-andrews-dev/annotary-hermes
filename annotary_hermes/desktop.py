"""The Annotary page is this package's desktop half, ``desktop/plugin.js``.

Hermes publishes it to ``<root>/desktop-plugins/annotary/`` with its ``.hermes-package.json`` marker
(Electron in native Desktop, the Webapp's routes on the host), so the page and the agent half are one
plugin. Earlier versions copied the page there themselves with no marker. Hermes treats a marker-less
folder as a plugin the user put there and never publishes the half over it, so that copy is removed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import paths

MARKER = ".hermes-package.json"
#: Every page this plugin ever copied in declares this; a folder without it is not ours to remove.
LEGACY_SIGNATURE = "const ID = 'annotary'"


def source() -> Path:
    return paths.package_dir() / "desktop" / "plugin.js"


def valid_marker(target: Path) -> dict | None:
    """The package marker as Hermes reads it (``read_package_marker``): a dict naming ``package`` and
    ``source``. Anything else Hermes treats as no marker, so this does too."""
    try:
        marker = json.loads((target / MARKER).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) and marker.get("package") and marker.get("source") else None


def _is_link(target: Path) -> bool:
    """A symlink or a Windows junction (a linked dev checkout): never ours to delete through."""
    return target.is_symlink() or getattr(target, "is_junction", lambda: False)()


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:  # missing, or Hermes's staged rename landed mid-read
        return None


def is_standalone_copy(target: Path) -> bool:
    """The page an earlier version copied in by hand: a real folder holding only ``plugin.js``, our
    page, with no marker Hermes would accept, and not byte-equal to the current half (Hermes adopts
    that copy itself by stamping its marker, so removing it would only race that)."""
    js = target / "plugin.js"
    if _is_link(target) or not target.is_dir() or valid_marker(target) is not None:
        return False
    try:
        if {e.name for e in target.iterdir()} - {MARKER} != {"plugin.js"}:
            return False
    except OSError:
        return False
    body = _read(js)
    return body is not None and LEGACY_SIGNATURE.encode() in body and body != _read(source())


def page_status(root: Path | None = None) -> dict:
    target = paths.desktop_page_target(root)
    body, current = _read(target / "plugin.js"), _read(source())
    status: dict = {"path": str(target), "present": body is not None, "paired": valid_marker(target) is not None,
                    "standalone_copy": is_standalone_copy(target)}
    status["current"] = body is not None and body == current
    status["ok"] = status["present"] and status["paired"] and status["current"]
    return status


def retire_standalone_page(root: Path | None = None) -> bool:
    """Remove an earlier version's hand-copied page, so Hermes can publish the package's half there.
    Returns whether it did; a folder that cannot be removed is left for ``doctor`` to report."""
    target = paths.desktop_page_target(root)
    if not is_standalone_copy(target):
        return False
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return True
