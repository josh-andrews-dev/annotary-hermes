"""Each Bot's Bot Mode face on its Annotary Member, so it shows next to the Bot's comments.

A face comes from ``profile.yaml`` (``ui_meta['hermes-bots']``), or from the profile's name when
nothing is stored, the way Desktop draws it. Standard library only.

Desktop's ``assets/avatar.png`` is not used for a face this module can draw: Desktop writes that
160 px copy once per profile and never again, so after a shape or color edit it shows the old face.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from . import accounts, blobatar, hermes_face, server, state

log = logging.getLogger(__name__)

ASSET_EXTS = ("png", "jpg", "webp")  # Hermes's own list (profiles.set_asset)
_STILL_SIZE = 160  # Desktop's own raster of a drawn face (avatar-image.ts, isBackfilledFacePng)


@dataclass(frozen=True)
class Face:
    image: bytes
    static: bytes | None = None

    @property
    def hash(self) -> str:
        h = hashlib.sha256(self.image)
        h.update(b"\0")
        h.update(self.static or b"")
        return h.hexdigest()[:32]


def _meta(home: Path) -> dict:
    ui = accounts._read_profile_yaml(home / "profile.yaml").get("ui_meta")
    bots = ui.get("hermes-bots") if isinstance(ui, dict) else None
    return bots if isinstance(bots, dict) else {}


def _asset(home: Path) -> Path | None:
    for ext in ASSET_EXTS:
        p = home / "assets" / f"avatar.{ext}"
        if p.is_file():
            return p
    return None


def _is_desktop_still(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return False
    return (head[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(head[16:20], "big") == _STILL_SIZE
            and int.from_bytes(head[20:24], "big") == _STILL_SIZE)


def _as_is(asset: Path | None) -> Face | None:
    return Face(asset.read_bytes()) if asset else None


def face_for(pid: str, home: Path) -> Face | None:
    """The face Desktop shows for this profile, or None when there is nothing to show."""
    meta, asset = _meta(home), _asset(home)
    if meta.get("pet"):
        return _as_is(asset)  # a petdex sprite: only Desktop can draw it
    kind = meta.get("imageKind")
    if asset and (kind == "photo" or (kind is None and not _is_desktop_still(asset))):
        return _as_is(asset)
    shape, color = hermes_face.appearance(pid, meta)
    if blobatar.is_recipe(shape):
        return Face(blobatar.face(shape, pid).svg(64).encode())  # static in Desktop too
    if shape.startswith("sigil-"):
        return _as_is(asset)  # line art, drawn from code this port does not carry
    return Face(hermes_face.animated_svg(shape, color).encode(), hermes_face.static_png(shape, color))


def _upload(tok: str, face: Face) -> None:
    body = {"image": base64.b64encode(face.image).decode("ascii")}
    if face.static:
        body["static"] = base64.b64encode(face.static).decode("ascii")
    server.api(tok, "PUT", "/api/v1/me/avatar", body)


class _NoAvatars(Exception):
    """The running server is older than Member avatars."""


def _apply(pid: str, entry: dict, home: Path, root: Path | None) -> str | None:
    """Bring one Member's avatar up to date: its new hash ("" for none), or None when unchanged."""
    tok = accounts.token_for(pid, root)
    if not tok:
        return None
    face = face_for(pid, home)
    want = face.hash if face else ""
    if want == entry.get("avatar", ""):
        return None
    try:
        if face:
            _upload(tok, face)
        else:
            server.api(tok, "DELETE", "/api/v1/me/avatar")
    except server.ServerError as e:
        if getattr(e, "status", None) == 404:
            raise _NoAvatars from None
        raise
    return want


def sync(root: Path | None = None) -> dict[str, str]:
    """Upload each Bot's face when it has changed. Returns only failures: one never stops a
    reconcile, is reported once (until the reason changes) and is tried again on the next pass."""
    report: dict[str, str] = {}
    members = state.load(root)["members"]
    done: dict[str, dict] = {}
    for p in accounts.list_profiles(root):
        entry = members.get(p.id)
        if not entry or entry.get("disabled"):
            continue
        try:
            new = _apply(p.id, entry, p.home, root)
        except _NoAvatars:
            log.debug("annotary: this server has no Member avatars")
            break
        except Exception as e:  # noqa: BLE001 — an avatar is decoration: nothing here may stop a reconcile
            reason = str(e)[:200] or type(e).__name__
            if entry.get("avatar_error") != reason:
                report[p.id] = f"avatar not set: {reason}"
                done[p.id] = {"avatar_error": reason}
            continue
        if new is not None:
            done[p.id] = {"avatar": new}
        elif entry.get("avatar_error"):
            done[p.id] = {}

    def record(st: dict) -> None:
        for pid, fields in done.items():
            entry = st["members"].get(pid)
            if entry is not None:
                if "avatar_error" not in fields:
                    entry.pop("avatar_error", None)
                entry.update(fields)

    if done:
        state.update(record, root)
    return report
