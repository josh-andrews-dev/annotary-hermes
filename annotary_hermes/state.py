"""The plugin's shared state, ``<root>/annotary/state.json``, guarded by an flock.

Every profile (in the gateway, its plugin host, or a ``hermes`` command) reads and writes the same
file, so it holds only what must be shared: which Member each profile is, each Document's editor
and sharing session, wake-up bookkeeping. No secrets: Tokens live in their own mode-600 files.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterator

from . import paths


def _file(root: Path | None = None) -> Path:
    return paths.app_dir(root) / "state.json"


@contextlib.contextmanager
def locked(name: str, root: Path | None = None, *, blocking: bool = True) -> Iterator[bool]:
    """Hold ``<root>/annotary/<name>.lock``. Non-blocking: yields False when another holds it."""
    f = open(paths.app_dir(root) / f"{name}.lock", "a+")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()


def _empty() -> dict:
    return {"members": {}, "docs": {}, "sessions": {}, "pending": {}, "agent_wakes": {},
            "hinted": {}, "cursors": {}}


def _read(root: Path | None = None) -> dict:
    try:
        data = json.loads(_file(root).read_text())
    except (OSError, ValueError):
        data = {}
    base = _empty()
    base.update(data if isinstance(data, dict) else {})
    return base


def load(root: Path | None = None) -> dict:
    with locked("state", root):
        return _read(root)


def update(fn: Callable[[dict], Any], root: Path | None = None) -> Any:
    """Run *fn(state)* under the lock and write the state back; returns what *fn* returned."""
    with locked("state", root):
        data = _read(root)
        result = fn(data)
        target = _file(root)
        tmp = target.with_name(f".state.json.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, target)
        return result
