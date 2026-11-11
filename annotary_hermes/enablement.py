"""Whether each Hermes profile has the plugin, read from its files (no `hermes` subprocess).

Hermes scans only a profile's own `plugins/` folder and loads a third-party plugin only when the
profile's `config.yaml` lists it under `plugins.enabled`. So a profile made with `hermes profile
create` after install has no Annotary until it is linked and enabled, and a profile cloned from
default (Desktop's Bot Mode) gets the plugin enabled but as its own copy, which a plugin update
never reaches. `hermes annotary enable --all` fixes both. A profile where the person turned the
plugin off stays off: only `hermes annotary enable <profile>` brings it back.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import shutil
from pathlib import Path

from . import paths

ON, OFF, COPY, DECLINED = "on", "off", "copy", "declined"


def _inline_list(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    return [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]


def parse_plugin_lists(text: str) -> dict[str, list[str]]:
    """``plugins.enabled`` and ``plugins.disabled`` from a config.yaml's text, without PyYAML:
    block lists (``- name``) or inline ones (``[a, b]``), comments and blank lines skipped."""
    out: dict[str, list[str]] = {"enabled": [], "disabled": []}
    in_plugins, child, key = False, None, None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_plugins, child, key = stripped == "plugins:", None, None
            continue
        if not in_plugins:
            continue
        child = indent if child is None else child
        if indent == child:
            m = re.match(r"([A-Za-z_][\w-]*):\s*(.*)$", stripped)
            key = m.group(1) if m and m.group(1) in out else None
            if key and m:
                out[key].extend(_inline_list(m.group(2)))
        elif key and indent > child and stripped.startswith("- "):
            out[key].append(stripped[2:].split("#")[0].strip().strip("'\""))
    return out


def plugin_lists(home: Path) -> dict[str, list[str]]:
    try:
        text = (home / "config.yaml").read_text(encoding="utf-8")
    except OSError:
        return {"enabled": [], "disabled": []}
    try:
        import yaml  # Hermes depends on PyYAML
    except ImportError:
        return parse_plugin_lists(text)
    try:
        data = yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — a config Hermes itself could not read: treat as not enabled
        return {"enabled": [], "disabled": []}
    plugins = data.get("plugins") if isinstance(data, dict) else None
    plugins = plugins if isinstance(plugins, dict) else {}
    return {k: [str(x) for x in plugins[k]] if isinstance(plugins.get(k), list) else []
            for k in ("enabled", "disabled")}


def _is_this_plugin(folder: Path) -> bool:
    if not (folder / "annotary_hermes").is_dir():  # another plugin may also call itself annotary
        return False
    try:
        text = (folder / "plugin.yaml").read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(rf"^name:\s*['\"]?{paths.PLUGIN_ID}['\"]?\s*$", text, re.M) is not None


def plugin_state(pid: str, root: Path | None = None) -> str:
    """ON; COPY (enabled, but running its own copy of the plugin, not a link to the installed
    one); OFF (never set up: no plugin folder); or DECLINED (the person turned it off here: listed
    under ``plugins.disabled``, or in the folder but not enabled)."""
    home = paths.profile_home(pid, root)
    lists = plugin_lists(home)
    here = home / "plugins" / paths.PLUGIN_ID
    if paths.PLUGIN_ID in lists["disabled"]:
        return DECLINED
    if not here.exists():
        return OFF
    if paths.PLUGIN_ID not in lists["enabled"]:
        return DECLINED
    if pid == "default" or here.is_symlink() or here.parent.is_symlink():
        return ON
    # Its own folder: Hermes's per-profile install ("Install here") puts one there too. Only one
    # whose code differs from the default profile's install is a stale copy.
    main = paths.profile_home("default", root) / "plugins" / paths.PLUGIN_ID
    return ON if _is_this_plugin(main) and fingerprint(here) == fingerprint(main) else COPY


#: The files that make the plugin's behavior; equal fingerprints mean the same plugin code.
_CODE_GLOBS = ("plugin.yaml", "__init__.py", "annotary_hermes/*.py", "dashboard/*.py", "desktop/*.js",
               "skills/annotary/SKILL.md")


def fingerprint(folder: Path) -> str:
    h = hashlib.sha256()
    for pattern in _CODE_GLOBS:
        for f in sorted(folder.glob(pattern)):
            try:
                h.update(f.relative_to(folder).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
            except OSError:
                h.update(b"?")
    return h.hexdigest()


def has_annotary(state: str) -> bool:
    return state in (ON, COPY)


def _finish_interrupted_replace(here: Path, aside_dir: Path) -> None:
    """A replacement cut off after moving the copy aside: put it back. Other leftovers go."""
    leftovers = sorted(aside_dir.glob(".replaced-*"))
    if leftovers and not here.exists() and not here.is_symlink():
        leftovers.pop().rename(here)
    for old in leftovers:
        shutil.rmtree(old, ignore_errors=True)


def link_plugin(pid: str, root: Path | None = None) -> str:
    """Make *pid*'s ``plugins/annotary`` a link to the installed plugin. A copy of this plugin
    (from a clone) is replaced by the link; anything else is left alone. Returns what it did."""
    root = paths.hermes_root() if root is None else root
    if pid == "default":
        return "the installed plugin"
    installed = root / "plugins" / paths.PLUGIN_ID
    target = (installed if installed.exists() else paths.package_dir()).resolve()
    here = paths.profile_home(pid, root) / "plugins" / paths.PLUGIN_ID
    aside_dir = paths.profile_home(pid, root) / "plugin-data" / paths.PLUGIN_ID
    _finish_interrupted_replace(here, aside_dir)
    if not target.is_dir():
        return "left as is: the installed plugin is missing"
    if here.is_symlink():
        return "linked" if here.resolve() == target else f"left as is: links to {here.resolve()}"
    if here.exists():
        # The same folder by another path (a linked plugins/): moving it would destroy the plugin.
        if here.resolve() == target:
            return "left as is: this is the installed plugin"
        if not _is_this_plugin(here):
            return "left as is: not this plugin"
        # Moved out of plugins/ first, so Hermes never sees two copies, then removed.
        aside = aside_dir / f".replaced-{secrets.token_hex(4)}"
        aside.parent.mkdir(parents=True, exist_ok=True)
        here.rename(aside)
        try:
            here.symlink_to(target, target_is_directory=True)
        except OSError as e:
            aside.rename(here)
            return f"left as is: could not link it ({e})"
        except BaseException:
            aside.rename(here)
            raise
        shutil.rmtree(aside, ignore_errors=True)
        return "replaced its own copy with a link"
    here.parent.mkdir(parents=True, exist_ok=True)
    here.symlink_to(target, target_is_directory=True)
    return "linked"


def unlink_plugin(pid: str, root: Path | None = None) -> None:
    """Take back a link whose enable failed: linked but not enabled reads as DECLINED."""
    here = paths.profile_home(pid, root) / "plugins" / paths.PLUGIN_ID
    if here.is_symlink():
        here.unlink()


FIX = "hermes annotary enable --all"


def turn_on(pid: str) -> str:
    return f"hermes annotary enable {pid}"


SAY = {
    OFF: f"Annotary is off in this profile (its agent has no Annotary tools or skill): run `{FIX}`",
    COPY: f"this profile runs an older copy of the plugin than the default profile's: run `{FIX}`",
}
