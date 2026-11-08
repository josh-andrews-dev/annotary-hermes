"""Put the Annotary page in place as a standalone desktop plugin.

Hermes loads a package's desktop half (``desktop/plugin.js``, copied with a ``.hermes-package.json``
marker) switched off in each new browser, and the Capabilities page that switches it on fails in
Safari on Hermes 0.23. A desktop plugin folder with no marker loads switched on everywhere. So the
package ships its page as ``desktop-page/plugin.js``, a name Hermes's own half-copier never reads
(it looks only at ``plugin.js`` and ``desktop/plugin.js``), and this module copies it to
``<root>/desktop-plugins/annotary/`` with no marker. Hermes then never pairs, adopts or prunes it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from . import paths

MARKER = ".hermes-package.json"


def source() -> Path:
    return paths.package_dir() / "desktop-page" / "plugin.js"


def page_status(root: Path | None = None) -> dict:
    target = paths.desktop_page_target(root)
    js = target / "plugin.js"
    status: dict = {"path": str(target), "present": js.is_file()}
    if (target / MARKER).exists():
        try:
            status["marker"] = json.loads((target / MARKER).read_text())
        except (OSError, ValueError):
            status["marker"] = "unreadable"
    status["current"] = js.is_file() and source().is_file() and js.read_bytes() == source().read_bytes()
    status["ok"] = status["present"] and status["current"] and "marker" not in status
    return status


def install_page(root: Path | None = None) -> dict:
    """Copy the page in place (staged, then renamed), with no marker. Returns what it did; a marker
    found in the folder is reported, since it means something adopted the folder as a package half."""
    before = page_status(root)
    if before["ok"]:
        return {"changed": False, **before}
    src = source()
    if not src.is_file():
        raise FileNotFoundError(f"the package has no desktop page at {src}")
    target = paths.desktop_page_target(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        staged = staging / target.name
        staged.mkdir()
        shutil.copyfile(src, staged / "plugin.js")
        os.chmod(staged / "plugin.js", 0o644)
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        os.rename(staged, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"changed": True, "removed_marker": before.get("marker"), **page_status(root)}
