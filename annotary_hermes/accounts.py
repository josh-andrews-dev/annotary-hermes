"""One Annotary Member per Hermes profile, kept in step with the profile list (D3, D4).

Profiles have no lifecycle events, so this is a reconcile: list the profiles, then create a Member
for a new one, follow a renamed one through ``previous_names`` (same Member, same handle), keep the
display name in step with the Bot's title, and disable the Member of a profile that is gone.
Handles never change and are never reused (Annotary's rule).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, server, state

RECONCILE_EVERY = 60  # seconds, at most, from tool and backend calls
GATEWAY_RECONCILE_EVERY = 300
_IDENTITY_FILES = ("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")


@dataclass
class Profile:
    id: str
    home: Path
    display_name: str = ""
    bot_title: str = ""
    previous_names: list[str] = field(default_factory=list)


def _yaml_scalar(v: str):
    return {"true": True, "false": False, "null": None}.get(v.lower(), v)


def _read_profile_yaml(path: Path) -> dict:
    """``profile.yaml`` as a dict. PyYAML when Hermes has it; else a reader for the few keys used
    here (top-level strings, a list of strings, the scalars under ``ui_meta: hermes-bots``)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    try:
        import yaml  # Hermes depends on PyYAML
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — a broken file is "no metadata", as Hermes reads it
        return {}
    data: dict = {}
    key = None
    stack: list[str] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- ") and key:
            data.setdefault(key, []).append(line[2:].strip().strip("'\""))
            continue
        m = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip().strip("'\"")
        if indent == 0:
            stack = [k]
            key = k
            if v:
                data[k] = v
        else:
            stack = stack[: max(1, indent // 2)] + [k]
            if stack[:2] == ["ui_meta", "hermes-bots"] and len(stack) == 3 and v:
                data.setdefault("ui_meta", {}).setdefault("hermes-bots", {})[stack[2]] = _yaml_scalar(v)
    return data


def read_profile(pid: str, home: Path) -> Profile:
    data = _read_profile_yaml(home / "profile.yaml")
    bots = (data.get("ui_meta") or {}).get("hermes-bots") if isinstance(data.get("ui_meta"), dict) else None
    title = str((bots or {}).get("title") or "").strip() if isinstance(bots, dict) else ""
    prev = data.get("previous_names") or []
    return Profile(id=pid, home=home, display_name=str(data.get("display_name") or "").strip(),
                   bot_title=title,
                   previous_names=[str(p).strip() for p in prev if str(p).strip()] if isinstance(prev, list) else [])


def _is_live(home: Path) -> bool:
    try:
        from hermes_constants import named_profile_is_live
        return bool(named_profile_is_live(home))
    except ImportError:
        return home.is_dir() and any((home / f).exists() for f in _IDENTITY_FILES)


def list_profiles(root: Path | None = None) -> list[Profile]:
    root = root or paths.hermes_root()
    out = [read_profile("default", root)]
    pdir = root / "profiles"
    if pdir.is_dir():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and _is_live(d):
                out.append(read_profile(d.name, d))
    return out


def desired_handle(p: Profile, owner: str) -> str:
    """The Bot Mode tag (D3): a named profile's name; the default profile's own name when it has
    one, else ``hermes``. ``-agent`` on a clash with the person's handle."""
    if p.id == "default":
        h = server.slug(p.display_name) or server.slug(p.bot_title) or "hermes"
    else:
        h = server.slug(p.id) or "agent"
    return f"{h}-agent" if h == owner else h


def display_name(p: Profile) -> str:
    """The Bot's title: Bot Mode's title, else the profile's display name, else its id."""
    return p.bot_title or p.display_name or ("Hermes" if p.id == "default" else p.id)


def _write_token(pid: str, token: str, root: Path | None) -> None:
    paths.write_secret(paths.token_path(pid, root), token + "\n")


def token_for(pid: str, root: Path | None = None) -> str | None:
    try:
        return paths.token_path(pid, root).read_text().strip() or None
    except OSError:
        return None


def _members(owner_tok: str) -> dict[str, dict]:
    return {m["handle"]: m for m in server.api(owner_tok, "GET", "/api/v1/members")["members"]}


def _add_member(owner_tok: str, handle: str, name: str, root: Path | None) -> str:
    r = server.run_cli(owner_tok, ["member", "add", handle, "--name", name, "--json"], root=root)
    if r.returncode != 0:
        raise server.ServerError(f"member add @{handle}: {r.stderr.strip()[-200:]}")
    return json.loads(r.stdout)["token"]


def _mint(owner_tok: str, handle: str, root: Path | None) -> str:
    r = server.run_cli(owner_tok, ["token", "mint", "--member", handle, "--name", "hermes", "--json"], root=root)
    if r.returncode != 0:
        raise server.ServerError(f"token mint @{handle}: {r.stderr.strip()[-200:]}")
    data = json.loads(r.stdout)
    return data.get("token") or data.get("plain") or ""


def _enable(owner_tok: str, handle: str, root: Path | None) -> str:
    """Enable a disabled Member again (same handle, Grants and history) and mint its new Token:
    ``member enable`` keeps the old Tokens revoked."""
    r = server.run_cli(owner_tok, ["member", "enable", handle], root=root)
    if r.returncode != 0:
        raise server.ServerError(f"member enable @{handle}: {r.stderr.strip()[-200:]}")
    return _mint(owner_tok, handle, root)


def reconcile(root: Path | None = None) -> dict:
    """Bring Members in step with the profiles. Returns {profile: what happened}."""
    owner_tok = server.owner_token(root)
    owner = server.owner_handle(root)
    profiles = {p.id: p for p in list_profiles(root)}
    remote = _members(owner_tok)
    report: dict[str, str] = {}

    def note(pid: str, what: str) -> None:
        report[pid] = f"{report[pid]}; {what}" if pid in report else what

    def work(st: dict) -> None:
        mapped: dict = st["members"]
        # Renames first: a mapped profile that is gone but named in a live profile's previous_names.
        for old in [k for k in mapped if k not in profiles]:
            new = next((p.id for p in profiles.values() if old in p.previous_names and p.id not in mapped), None)
            if new:
                mapped[new] = {**mapped.pop(old), "renamed_from": old}
                for doc in st["docs"].values():
                    if doc.get("editor") == old:
                        doc["editor"] = new
                note(new, f"renamed from {old}, keeps @{mapped[new]['handle']}")
        for pid, entry in list(mapped.items()):
            if pid in profiles or entry.get("disabled"):
                continue
            server.api(owner_tok, "POST", f"/api/v1/members/{entry['handle']}/disable", {})
            entry["disabled"] = True
            entry["disabled_at"] = time.time()
            note(pid, f"profile gone, @{entry['handle']} disabled")
        taken = set(remote)
        for pid, p in profiles.items():
            name = display_name(p)
            entry = mapped.get(pid)
            if entry and entry.get("disabled"):
                try:
                    tok = _enable(owner_tok, entry["handle"], root)
                except server.ServerError as e:  # the next pass tries again
                    note(pid, f"profile back, @{entry['handle']} not enabled yet: {e}")
                    continue
                _write_token(pid, tok, root)
                entry.pop("disabled", None)
                entry.pop("disabled_at", None)
                entry.pop("needs_enable", None)  # written by earlier versions of this plugin
                note(pid, f"profile back, @{entry['handle']} enabled")
                continue
            if entry is None:
                handle = desired_handle(p, owner)
                base, n = handle, 2
                while handle in taken:
                    handle = f"{base}-{n}"
                    n += 1
                tok = _add_member(owner_tok, handle, name, root)
                _write_token(pid, tok, root)
                taken.add(handle)
                mapped[pid] = {"handle": handle, "name": name}
                note(pid, f"added @{handle}")
                continue
            if remote.get(entry["handle"], {}).get("name", entry.get("name")) != name:
                r = server.run_cli(owner_tok, ["member", "rename", entry["handle"], name], root=root)
                if r.returncode == 0:
                    entry["name"] = name
                    note(pid, f"@{entry['handle']} display name -> {name}")
            if not token_for(pid, root):
                _write_token(pid, _mint(owner_tok, entry["handle"], root), root)
                note(pid, f"@{entry['handle']} new Token")
        st["reconciled_at"] = time.time()

    state.update(work, root)
    from . import avatars  # avatars imports this module
    for pid, what in avatars.sync(root).items():
        note(pid, what)
    return report


def reconcile_if_due(root: Path | None = None, every: float = RECONCILE_EVERY) -> dict | None:
    if time.time() - float(state.load(root).get("reconciled_at") or 0) < every:
        return None
    with state.locked("reconcile", root, blocking=False) as got:
        if not got:
            return None
        return reconcile(root)


def handles(root: Path | None = None) -> dict[str, str]:
    """handle -> profile for every Member this plugin manages (enabled or not)."""
    return {v["handle"]: k for k, v in state.load(root)["members"].items()}


def active_handles(root: Path | None = None) -> dict[str, str]:
    """handle -> profile for the enabled Members only: who may edit or be handed a Document."""
    return {v["handle"]: k for k, v in state.load(root)["members"].items() if not v.get("disabled")}


def handle_of(pid: str, root: Path | None = None) -> str | None:
    entry = state.load(root)["members"].get(pid)
    return entry["handle"] if entry else None
