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


def _marker(target: Path):
    try:
        return json.loads((target / MARKER).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return "unreadable"


def is_standalone_copy(target: Path) -> bool:
    """The page an earlier version copied in by hand: a real folder, no package marker, our page."""
    js = target / "plugin.js"
    if target.is_symlink() or (target / MARKER).exists() or not js.is_file():
        return False
    try:
        return LEGACY_SIGNATURE in js.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def page_status(root: Path | None = None) -> dict:
    target = paths.desktop_page_target(root)
    js = target / "plugin.js"
    status: dict = {"path": str(target), "present": js.is_file(), "paired": _marker(target) is not None,
                    "standalone_copy": is_standalone_copy(target)}
    status["current"] = js.is_file() and source().is_file() and js.read_bytes() == source().read_bytes()
    status["ok"] = status["present"] and status["paired"] and status["current"]
    return status


def retire_standalone_page(root: Path | None = None) -> bool:
    """Remove an earlier version's hand-copied page, so Hermes can publish the package's half there."""
    target = paths.desktop_page_target(root)
    if not is_standalone_copy(target):
        return False
    shutil.rmtree(target)
    return True
