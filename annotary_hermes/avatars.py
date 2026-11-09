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
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from . import accounts, blobatar, hermes_face, server, state

log = logging.getLogger(__name__)

ASSET_EXTS = ("png", "jpg", "webp")  # Hermes's own list (profiles.set_asset)
_STILL_SIZE = 160  # Desktop's own raster of a drawn face (avatar-image.ts, isBackfilledFacePng)
_MAX_PICTURE = 256 * 1024  # Annotary refuses a larger image
_STILL_FORMAT = b"frame0-png-1"  # change it when static_png's output changes, so every still is sent again


@dataclass(frozen=True)
class Face:
    image: bytes
    draw_static: Callable[[], bytes] | None = None

    @cached_property
    def static(self) -> bytes | None:
        return self.draw_static() if self.draw_static else None

    @property
    def hash(self) -> str:
        """Of the image alone: a still is drawn from the same shape and color as its SVG, so the
        SVG's bytes cover it, and a pass with nothing to upload draws nothing."""
        h = hashlib.sha256(self.image)
        h.update(b"\0")
        h.update(_STILL_FORMAT if self.draw_static else b"")
        return h.hexdigest()[:32]


def _meta(home: Path) -> dict:
    ui = accounts._read_profile_yaml(home / "profile.yaml").get("ui_meta")
    bots = ui.get("hermes-bots") if isinstance(ui, dict) else None
    return bots if isinstance(bots, dict) else {}


def _is_picture(data: bytes) -> bool:
    return (data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def _picture(home: Path) -> bytes | None:
    """The profile's own ``assets/avatar.*``, if it is one Annotary can take."""
    for ext in ASSET_EXTS:
        path = home / "assets" / f"avatar.{ext}"
        if not accounts.own_file(path, home):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read(_MAX_PICTURE + 1)
        except OSError:
            continue
        if len(data) <= _MAX_PICTURE and _is_picture(data):
            return data
    return None


def _is_desktop_still(data: bytes) -> bool:
    return (data[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(data[16:20], "big") == _STILL_SIZE
            and int.from_bytes(data[20:24], "big") == _STILL_SIZE)


def face_for(pid: str, home: Path) -> Face | None:
    """The face Desktop shows for this profile, or None when there is nothing to show."""
    meta, picture = _meta(home), _picture(home)
    as_is = Face(picture) if picture else None
    if meta.get("pet"):
        return as_is  # a petdex sprite: only Desktop can draw it
    kind = meta.get("imageKind")
    if picture and (kind == "photo" or (kind is None and not _is_desktop_still(picture))):
        return as_is
    shape, color = hermes_face.appearance(pid, meta)
    if blobatar.is_recipe(shape):
        return Face(blobatar.face(shape, pid).svg(64).encode())  # static in Desktop too
    if shape.startswith("sigil-"):
        return as_is  # line art, drawn from code this port does not carry
    return Face(hermes_face.animated_svg(shape, color).encode(), lambda: hermes_face.static_png(shape, color))


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
