"""One Annotary Member per Hermes profile, kept in step with the profile list (D3, D4).

Profiles have no lifecycle events, so this is a reconcile: list the profiles, then create a Member
for a new one, follow a renamed one through ``previous_names`` (same Member, same handle), keep the
display name in step with the Bot's title, and disable the Member of a profile that is gone.
Handles never change and are never reused (Annotary's rule).
"""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import enablement, paths, server, state

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


def own_file(path: Path, home: Path) -> bool:
    """*path* is a regular file, not a link, that really lives under *home*: a link could point
    anywhere, and what is read from a profile may be uploaded."""
    try:
        return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(home.resolve())
    except (OSError, RuntimeError):  # RuntimeError: a symlink loop
        return False


def _yaml_scalar(v: str):
    return {"true": True, "false": False, "null": None}.get(v.lower(), v)


def _read_profile_yaml(path: Path) -> dict:
    """``profile.yaml`` as a dict. PyYAML when Hermes has it; else a reader for the few keys used
    here (top-level strings, a list of strings, the scalars under ``ui_meta: hermes-bots``)."""
    if not own_file(path, path.parent):
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):  # one unreadable profile must not stop the others
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
            items = data.setdefault(key, [])
            if isinstance(items, list):
                items.append(line[2:].strip().strip("'\""))
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
            ui = data.setdefault("ui_meta", {}) if stack[:1] == ["ui_meta"] else None
            if isinstance(ui, dict) and stack[1:2] == ["hermes-bots"] and len(stack) == 3 and v:
                ui.setdefault("hermes-bots", {})[stack[2]] = _yaml_scalar(v)
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
    """Bring Members in step with the profiles. Returns {profile: what happened}. Holds the
    ``owner`` lock, so it never acts with an owner Token that ``name_person`` is retiring."""
    with state.locked("owner", root):
        return _reconcile(root)


def _reconcile(root: Path | None) -> dict:
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
        for pid in profiles:
            entry = mapped.get(pid)
            if not entry or entry.get("disabled"):
                continue
            plugin = enablement.plugin_state(pid, root)
            if plugin != entry.get("plugin", enablement.ON) and plugin != enablement.DECLINED:
                note(pid, enablement.SAY.get(plugin, "Annotary is on in this profile"))
            entry["plugin"] = plugin
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


MAX_NAME = 64


def _ascii_slug(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return server.slug(folded)


def person(root: Path | None = None) -> dict:
    """The person's own Member: handle, display name, and whether they gave a name yet."""
    handle = server.owner_handle(root)
    name = ""
    try:
        name = _members(server.owner_token(root)).get(handle, {}).get("name") or ""
    except server.ServerError:
        pass
    return {"handle": handle, "name": name, "named": server.owner_named(root)}


def name_person(name: str, root: Path | None = None) -> dict:
    """Give the person the *name* they chose. Handles never change, so while they still have
    setup's placeholder (``@owner``, or a service account's name) they get a new owner Member with
    a handle made from the name; the placeholder is renamed too (its Comments read as theirs) and
    disabled. Once named, a new name changes only the display name. Returns ``person()``'s shape.

    Safe to run again after a failure at any step: the new handle is recorded before it is
    created and adopted on the next run, and every earlier placeholder still active is retired."""
    name = " ".join((name or "").split())
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"give a name of 1 to {MAX_NAME} characters")
    with state.locked("owner", root):
        old_tok, old = server.owner_token(root), server.owner_handle(root)
        want = _ascii_slug(name)
        remote = _members(old_tok)
        pending = server.naming_pending(root)
        live_pending = pending if pending and pending != old and pending in remote \
            and not remote[pending].get("disabled_at") else ""
        keep = server.owner_named(root) or not want or want == old
        if live_pending and (keep or not _made_from(live_pending, want)):
            # An earlier run under another name created it and stopped before the switch.
            server.api(old_tok, "POST", f"/api/v1/members/{live_pending}/disable", {})
            live_pending = ""
        if pending and not live_pending:
            server.update_secrets({"naming_pending": None}, root)
        if keep:
            server.api(old_tok, "POST", "/api/v1/me/rename", {"name": name})
            server.update_secrets({"owner_named": True}, root)
            _retire_placeholders(old_tok, name, root)
            return {"handle": old, "name": name, "named": True, "changed_handle": False}
        if live_pending:
            handle = live_pending  # an earlier run created it and stopped before the switch
            tok = _mint(old_tok, handle, root)
            if remote[handle].get("name") != name:
                _rename(old_tok, handle, name, root)
        else:
            bots = {m["handle"] for m in state.load(root)["members"].values()}
            handle, n = want, 2
            while handle in remote or handle in bots:
                handle = f"{want}-{n}"
                n += 1
            server.update_secrets({"naming_pending": handle}, root)
            tok = _add_member(old_tok, handle, name, root)
        r = server.run_cli(old_tok, ["member", "role", handle, "owner"], root=root)
        if r.returncode != 0:
            raise server.ServerError(f"member role @{handle} owner: {r.stderr.strip()[-200:]}")
        # A password closes loopback trust, and it must stay closed once the placeholder (which
        # holds setup's password) is disabled: give the new owner one first.
        password = secrets.token_urlsafe(32)
        server.api(tok, "PUT", "/api/v1/settings/password", {"password": password})
        server.update_secrets({"owner_handle": handle, "owner_token": tok, "owner_password": password,
                               "owner_named": True, "naming_pending": None,
                               "previous_owners": [*server.previous_owners(root), old]}, root)
        _retire_placeholders(tok, name, root)
        return {"handle": handle, "name": name, "named": True, "changed_handle": True, "was": old}


def _made_from(handle: str, want: str) -> bool:
    """Whether *handle* is the one naming picks for *want*: itself, or itself with a suffix."""
    return handle == want or re.fullmatch(re.escape(want) + r"-\d+", handle) is not None


def _rename(tok: str, handle: str, name: str, root: Path | None) -> None:
    r = server.run_cli(tok, ["member", "rename", handle, name], root=root)
    if r.returncode != 0:
        raise server.ServerError(f"member rename @{handle}: {r.stderr.strip()[-200:]}")


def _retire_placeholders(tok: str, name: str, root: Path | None) -> None:
    """Rename every earlier placeholder of the person to *name* and disable it. Raises on a
    failure, so the caller reports it; the next naming finishes the job."""
    remote = _members(tok)
    for h in server.previous_owners(root):
        m = remote.get(h)
        if not m:
            continue
        if m.get("name") != name:
            _rename(tok, h, name, root)
        if not m.get("disabled_at"):
            server.api(tok, "POST", f"/api/v1/members/{h}/disable", {})
