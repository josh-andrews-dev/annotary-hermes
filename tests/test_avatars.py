"""Bot faces (avatars.py, hermes_face.py, blobatar.py): fidelity to Hermes Desktop, the rules for
which face a profile gets, and the upload that reconcile runs.

The two fidelity checks that read an installed Hermes are read-only and run only where one is
installed. They are how a Hermes update that changes Desktop's face code fails here visibly.
"""

import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import pytest
from conftest import ROOT, make_profile

from annotary_hermes import accounts, avatars, blobatar, hermes_face, install, server, state

FIXTURES = ROOT / "tests" / "fixtures"
FACES_ROOT = Path(os.environ.get("ANNOTARY_HERMES_FACES_ROOT", Path.home() / ".hermes"))
DESKTOP = FACES_ROOT / "hermes-agent" / "apps" / "desktop"
# Desktop's functions this port follows. Re-check hermes_face.py, then update the pin.
PORTED = ("isDarkColor", "defaultShapeFor", "cubicAt", "sampleDropRing", "svgArc", "sampleArc", "sampleCloudRing",
          "sampleFaceRing", "projectFacePoint", "facePose", "botAppearance")
PORTED_SHA = "7313ab4e71c5cdd7"

SVG_ELEMENTS = {"svg", "g", "path", "circle", "ellipse", "rect", "polygon", "polyline", "line", "defs",
                "linearGradient", "radialGradient", "stop", "clipPath", "style", "title"}
SVG_ATTRIBUTES = {"id", "class", "fill", "stroke", "stroke-width", "stroke-linecap", "opacity", "cx", "cy", "r", "rx",
                  "ry", "d", "width", "height", "viewBox", "aria-hidden"}
CSS_FUNCTIONS = {"rotate", "scale", "translate", "hsl", "rgba", "rgb"}


def decode_png(data: bytes) -> tuple[int, int, list[bytes]]:
    """An 8-bit RGBA, non-interlaced PNG, as rows of bytes."""
    pos, idat, width, height = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, chunk = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", chunk[:10])
            assert (depth, color) == (8, 6)
        elif kind == b"IDAT":
            idat += chunk
    raw, stride, rows, prev, i = zlib.decompress(idat), width * 4, [], bytes(width * 4), 0
    for _ in range(height):
        f, row = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a, c, p = row[x - 4] if x >= 4 else 0, prev[x], prev[x - 4] if x >= 4 else 0
            if f == 1:
                row[x] = (row[x] + a) & 255
            elif f == 2:
                row[x] = (row[x] + c) & 255
            elif f == 3:
                row[x] = (row[x] + (a + c) // 2) & 255
            elif f == 4:
                q = a + c - p
                pa, pb, pc = abs(q - a), abs(q - c), abs(q - p)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else c if pb <= pc else p)) & 255
        rows.append(bytes(row))
        prev = bytes(row)
    return width, height, rows


def assert_same_face(desktop: bytes, name: str, meta=None):
    """Desktop drew its copy at some moment of the idle sway, so a few edge pixels differ."""
    shape, color = hermes_face.appearance(name, meta)
    w, h, want = decode_png(desktop)
    _, _, got = decode_png(hermes_face.static_png(shape, color, w))
    both = either = spread = 0
    for y in range(h):
        for x in range(w):
            a, b = want[y][x * 4 + 3] > 128, got[y][x * 4 + 3] > 128
            both += a and b
            either += a or b
            if a and b:
                spread += sum(abs(want[y][x * 4 + i] - got[y][x * 4 + i]) for i in range(3)) / 3
    assert both / either > 0.975, f"{name}: the outline differs from Desktop's ({both / either:.3f})"
    assert spread / both < 4, f"{name}: the colors differ from Desktop's ({spread / both:.1f} of 255)"


@pytest.mark.parametrize("name", ["default", "bencha", "benchb", "coder", "wfi-test"])
def test_frame_0_matches_the_png_desktop_drew(name):
    assert_same_face((FIXTURES / "desktop-faces" / f"{name}.png").read_bytes(), name)


def _installed_faces():
    homes = [("default", FACES_ROOT)] + [(p.name, p) for p in sorted((FACES_ROOT / "profiles").glob("*"))]
    for name, home in homes:
        png, config = home / "assets" / "avatar.png", home / "profile.yaml"
        meta = avatars._meta(home)
        shape, _ = hermes_face.appearance(name, meta)
        drawn = png.is_file() and avatars._is_desktop_still(png.read_bytes()) and not meta.get("pet")
        # Desktop writes this copy once, so one older than a face edit shows the earlier face.
        if drawn and not blobatar.is_recipe(shape) and not shape.startswith("sigil-") and (
                not config.is_file() or png.stat().st_mtime >= config.stat().st_mtime):
            yield pytest.param(name, png, meta, id=name)


@pytest.mark.parametrize("name, png, meta", list(_installed_faces()))
def test_frame_0_matches_the_faces_the_installed_desktop_drew(name, png, meta):
    assert_same_face(png.read_bytes(), name, meta)


def test_the_ported_desktop_code_is_the_code_hermes_ships():
    source = DESKTOP / "src" / "plugins" / "hermes-bots" / "avatar.tsx"
    if not source.is_file():
        pytest.skip("no Hermes Desktop source on this machine")
    text, parts = source.read_text(encoding="utf-8"), []
    for name in PORTED:
        m = re.search(rf"^(?:export )?function {name}\(.*?^}}$", text, re.S | re.M)
        assert m, f"Desktop no longer has {name}(): re-check annotary_hermes/hermes_face.py"
        parts.append(m.group(0))
    assert hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16] == PORTED_SHA, (
        "Hermes changed Desktop's face code: re-check annotary_hermes/hermes_face.py against it, then update PORTED_SHA")
    color = (DESKTOP / "src" / "lib" / "profile-color.ts").read_text(encoding="utf-8")
    assert "PROFILE_TAG_SATURATION = 68" in color and "PROFILE_TAG_LIGHTNESS = 58" in color


def test_the_blobatar_port_follows_the_release_hermes_ships():
    package = DESKTOP / "package.json"
    if not package.is_file():
        pytest.skip("no Hermes Desktop source on this machine")
    assert json.loads(package.read_text())["dependencies"]["blobatar"] == blobatar.VERSION


def test_the_blobatar_port_draws_what_the_library_draws():
    data = json.loads((FIXTURES / "blobatar_vectors.json").read_text())
    assert data["version"] == blobatar.VERSION
    for v in data["vectors"]:
        traits = {"shape": blobatar.BLOB_KIND_TRAIT[v["kind"]]} if v["kind"] else None
        assert blobatar.generate(v["seed"], traits).svg(64) == v["svg"], (v["seed"], v["kind"])


def test_a_pinned_silhouette_and_seed_read_as_in_desktop():
    assert blobatar.parse_recipe("blobatar", "coder") == ("coder", "")
    assert blobatar.parse_recipe("blobatar:abc", "coder") == ("abc", "")
    assert blobatar.parse_recipe("blobatar:abc:sun", "coder") == ("abc", "sun")
    assert blobatar.parse_recipe("blobatar::sun", "coder") == ("coder", "sun")
    assert blobatar.parse_recipe("blobatar::nope", "coder") == ("coder", "")


def test_a_named_profile_and_default_get_desktops_derived_look():
    assert hermes_face.appearance("default", None) == ("squircle", "#8b5cf6")
    assert hermes_face.appearance("default", {"shape": "pill"}) == ("squircle", "#8b5cf6")  # not customized
    assert hermes_face.appearance("default", {"shape": "pill", "color": "#112233", "custom": True}) == ("pill", "#112233")
    assert hermes_face.appearance("coder", None) == ("drop", "hsl(285 68% 58%)")
    assert hermes_face.appearance("coder", {"shape": "cloud"}) == ("cloud", "hsl(285 68% 58%)")


def test_pebble_uses_its_own_two_radii():
    ring = hermes_face.face_ring("pebble")
    assert ring[0] == pytest.approx((20, 20 - 15.2 * 1.06))  # the top
    assert ring[13] == pytest.approx((20 + 16.4 * 0.9, 20))  # the right


@pytest.mark.parametrize("color, rgb", [("#ff0000", (255, 0, 0)), ("#0f0", (0, 255, 0)), ("rgb(1, 2, 3)", (1, 2, 3)),
                                        ("hsl(0 100% 50%)", (255, 0, 0)), ("hsl(240, 100%, 50%)", (0, 0, 255))])
def test_colors_parse(color, rgb):
    r, g, b, a = hermes_face._parse_rgba(color)
    assert (round(r * 255), round(g * 255), round(b * 255), a) == (*rgb, 1)


@pytest.mark.parametrize("bad", ['"><script>x</script>', "red", "url(http://x)", "#12", 7, None])
def test_a_color_that_is_not_one_never_reaches_the_svg(bad):
    assert hermes_face.valid_color(bad) is None
    shape, color = hermes_face.appearance("coder", {"shape": "circle", "color": bad})
    assert color == "hsl(285 68% 58%)"
    assert "script" not in hermes_face.animated_svg(shape, color)


def assert_inside_the_allowlist(svg: str):
    root = ET.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    for el in root.iter():
        assert el.tag.split("}")[1] in SVG_ELEMENTS, el.tag
        assert set(el.attrib) <= SVG_ATTRIBUTES, el.attrib
    css = root.find("{http://www.w3.org/2000/svg}style").text
    assert set(re.findall(r"([a-z-]+)\(", css)) <= CSS_FUNCTIONS
    assert set(re.findall(r"@([a-z-]+)", css)) <= {"keyframes", "media"}


SHAPES = [*hermes_face.MATH_SHAPES, "pebble", "blob", "cube", "unknown-shape"]


@pytest.mark.parametrize("shape", SHAPES)
def test_every_classic_shape_animates_inside_the_allowlist_and_the_size_limit(shape):
    svg = hermes_face.animated_svg(shape, "#8b5cf6")
    assert_inside_the_allowlist(svg)
    assert "animation:" in svg and "prefers-reduced-motion" in svg
    assert len(svg.encode()) < 64 * 1024
    assert hermes_face.animated_svg(shape, "#8b5cf6") == svg  # deterministic, or every pass would upload
    assert len(hermes_face.static_png(shape, "#8b5cf6")) < 256 * 1024


def write_face(root, name, meta=None, asset=None, ext="png"):
    home = make_profile(root, name)
    if meta is not None:
        (home / "profile.yaml").write_text("ui_meta:\n  hermes-bots:\n" + "".join(
            f"    {k}: {json.dumps(v)}\n" for k, v in meta.items()))
    if asset is not None:
        (home / "assets").mkdir(exist_ok=True)
        (home / "assets" / f"avatar.{ext}").write_bytes(asset)
    return home


def still(size=160):
    return b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + struct.pack(">II", size, size) + b"rest"


def test_a_profile_with_nothing_stored_gets_the_animated_face_and_its_frame_0(tmp_path):
    f = avatars.face_for("coder", write_face(tmp_path, "coder"))
    assert f.image.startswith(b"<svg") and b"animation:" in f.image
    assert f.static.startswith(b"\x89PNG")


def test_a_stored_shape_and_color_win(tmp_path):
    f = avatars.face_for("coder", write_face(tmp_path, "coder", {"shape": "pill", "color": "#112233"}))
    assert f.image == hermes_face.animated_svg("pill", "#112233").encode()


def test_desktops_old_still_is_never_the_still_of_a_face_it_can_draw(tmp_path):
    home = write_face(tmp_path, "coder", {"shape": "pill", "color": "#112233", "imageKind": "shape"}, still())
    f = avatars.face_for("coder", home)
    assert f.static == hermes_face.static_png("pill", "#112233")


@pytest.mark.parametrize("meta, ext, size", [({"imageKind": "photo"}, "png", 160), ({"imageKind": "photo"}, "jpg", 256),
                                             ({}, "png", 256), (None, "webp", 512)])
def test_a_photo_is_uploaded_as_it_is(tmp_path, meta, ext, size):
    picture = still(size)
    f = avatars.face_for("coder", write_face(tmp_path, "coder", meta, picture, ext))
    assert (f.image, f.static) == (picture, None)


def test_a_blob_face_is_the_static_face_desktop_draws(tmp_path):
    f = avatars.face_for("coder", write_face(tmp_path, "coder", {"shape": "blobatar:abc:sun"}, still()))
    assert f.static is None and f.image == blobatar.face("blobatar:abc:sun", "coder").svg(64).encode()
    assert b"animation" not in f.image


@pytest.mark.parametrize("meta", [{"shape": "sigil-3"}, {"pet": "boba", "imageKind": "photo"}])
def test_what_cannot_be_drawn_falls_back_to_the_png_or_nothing(tmp_path, meta):
    assert avatars.face_for("coder", write_face(tmp_path, "coder", meta)) is None
    picture = still(96)
    f = avatars.face_for("bot", write_face(tmp_path, "bot", meta, picture))
    assert (f.image, f.static) == (picture, None)


def test_face_settings_read_without_pyyaml(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    home = make_profile(tmp_path, "bot")
    (home / "profile.yaml").write_text("display_name: Bot\nui_meta:\n  hermes-bots:\n    title: T\n    shape: pill\n"
                                       "    color: '#112233'\n    custom: false\n")
    assert avatars._meta(home) == {"title": "T", "shape": "pill", "color": "#112233", "custom": False}


class FakeApi:
    def __init__(self):
        self.calls, self.fail = [], {}

    def __call__(self, tok, method, path, body=None, **kw):
        self.calls.append((tok, method, path, body))
        err = self.fail.get(tok)
        if err:
            raise err
        return {}


def tokens(root):
    return {p: accounts.token_for(p, root) for p in ("default", "coder", "bencha")}


@pytest.fixture()
def fake_api(hermes, monkeypatch):
    accounts.reconcile()  # the Members exist, and this also uploaded
    state.update(lambda st: [m.pop("avatar", None) for m in st["members"].values()])
    api = FakeApi()
    monkeypatch.setattr(server, "api", api)
    return api


def http_error(status, message):
    e = server.ServerError(message)
    e.status = status
    return e


def puts(api):
    return [c for c in api.calls if c[1] == "PUT"]


def test_a_face_is_uploaded_once_and_again_only_when_it_changes(hermes, fake_api):
    assert avatars.sync() == {}
    assert len(puts(fake_api)) == 3 and all(c[2] == "/api/v1/me/avatar" for c in fake_api.calls)
    body = next(c[3] for c in puts(fake_api) if c[0] == tokens(hermes)["coder"])
    assert set(body) == {"image", "static"}
    fake_api.calls.clear()
    assert avatars.sync() == {}
    assert fake_api.calls == []
    (hermes / "profiles" / "coder" / "profile.yaml").write_text(
        "ui_meta:\n  hermes-bots:\n    shape: pill\n    color: '#112233'\n")
    assert avatars.sync() == {}
    assert [c[0] for c in fake_api.calls] == [tokens(hermes)["coder"]]


def test_each_bot_uploads_with_its_own_token(hermes, fake_api):
    avatars.sync()
    assert {c[0] for c in fake_api.calls} == set(tokens(hermes).values()) - {None}


def test_a_failed_upload_is_reported_once_and_tried_again(hermes, fake_api):
    t = tokens(hermes)
    fake_api.fail[t["coder"]] = http_error(413, "the avatar is too large")
    assert avatars.sync() == {"coder": "avatar not set: the avatar is too large"}
    assert len(puts(fake_api)) == 3  # the others went through
    assert "avatar" not in state.load()["members"]["coder"]
    fake_api.calls.clear()
    assert avatars.sync() == {}  # said once
    assert [c[0] for c in fake_api.calls] == [t["coder"]]  # and tried again
    fake_api.fail.clear()
    assert avatars.sync() == {}
    entry = state.load()["members"]["coder"]
    assert entry["avatar"] and "avatar_error" not in entry


def test_a_new_reason_is_reported(hermes, fake_api):
    t = tokens(hermes)
    fake_api.fail[t["coder"]] = http_error(400, "one")
    avatars.sync()
    fake_api.fail[t["coder"]] = http_error(400, "two")
    assert avatars.sync() == {"coder": "avatar not set: two"}


def test_a_face_that_cannot_be_rendered_stops_only_that_bot(hermes, fake_api, monkeypatch):
    real = avatars.face_for
    monkeypatch.setattr(avatars, "face_for", lambda pid, home: 1 / 0 if pid == "coder" else real(pid, home))
    assert avatars.sync() == {"coder": "avatar not set: division by zero"}
    assert len(puts(fake_api)) == 2


def test_a_server_without_the_route_is_reported_once_and_tried_again(hermes, fake_api):
    all_tokens = tokens(hermes).values()
    fake_api.fail.update({t: http_error(404, "not found") for t in all_tokens})
    first = avatars.sync()
    assert set(first) == set(tokens(hermes)) and all(v == "avatar not set: not found" for v in first.values())
    assert avatars.sync() == {}  # the same reason again says nothing
    assert len(puts(fake_api)) == 2 * len(all_tokens)  # every Bot, both passes: one 404 stops nobody else
    assert not any("avatar" in m for m in state.load()["members"].values())
    fake_api.fail.clear()
    assert avatars.sync() == {}
    assert all("avatar" in m and "avatar_error" not in m for m in state.load()["members"].values())


def test_a_face_that_goes_away_is_cleared_once(hermes, fake_api):
    home = hermes / "profiles" / "coder"
    (home / "assets").mkdir()
    (home / "assets" / "avatar.png").write_bytes(still(96))
    (home / "profile.yaml").write_text("ui_meta:\n  hermes-bots:\n    shape: sigil-1\n")
    avatars.sync()
    fake_api.calls.clear()
    (home / "assets" / "avatar.png").unlink()
    avatars.sync()
    assert [c[1:3] for c in fake_api.calls] == [("DELETE", "/api/v1/me/avatar")]
    assert state.load()["members"]["coder"]["avatar"] == ""
    fake_api.calls.clear()
    avatars.sync()
    assert fake_api.calls == []


def test_a_disabled_member_is_left_alone(hermes, fake_api):
    state.update(lambda st: st["members"]["coder"].update(disabled=True))
    avatars.sync()
    assert tokens(hermes)["coder"] not in {c[0] for c in fake_api.calls}


def test_reconcile_runs_the_upload_and_reports_its_failure(hermes, monkeypatch):
    accounts.reconcile()
    monkeypatch.setattr(avatars, "sync", lambda root=None: {"coder": "avatar not set: nope"})
    assert accounts.reconcile() == {"coder": "avatar not set: nope"}


# ------------------------------------------------------------------ what may be uploaded


PHOTO = {"imageKind": "photo", "shape": "pill", "color": "#112233"}
DRAWN = hermes_face.animated_svg("pill", "#112233").encode()


def outside_picture(tmp_path):
    secret = tmp_path / "elsewhere.png"
    secret.write_bytes(still(256))
    return secret


def test_a_symlinked_picture_is_never_read_and_the_drawn_face_is_used(tmp_path):
    home = write_face(tmp_path, "coder", PHOTO)
    (home / "assets").mkdir()
    (home / "assets" / "avatar.png").symlink_to(outside_picture(tmp_path))
    assert avatars.face_for("coder", home).image == DRAWN


def test_a_symlink_that_stays_inside_the_profile_is_refused_too(tmp_path):
    home = write_face(tmp_path, "coder", PHOTO)
    (home / "assets").mkdir()
    (home / "assets" / "elsewhere.png").write_bytes(still(256))
    (home / "assets" / "avatar.png").symlink_to("elsewhere.png")
    assert avatars.face_for("coder", home).image == DRAWN


def test_a_symlinked_assets_folder_is_not_followed_out_of_the_profile(tmp_path):
    home = write_face(tmp_path, "coder", PHOTO)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "avatar.png").write_bytes(still(256))
    (home / "assets").symlink_to(outside, target_is_directory=True)
    assert avatars.face_for("coder", home).image == DRAWN


def test_a_symlinked_profile_yaml_is_not_read(tmp_path):
    home = make_profile(tmp_path, "coder")
    secret = tmp_path / "other.yaml"
    secret.write_text("ui_meta:\n  hermes-bots:\n    shape: pill\n")
    (home / "profile.yaml").symlink_to(secret)
    assert avatars._meta(home) == {}


def test_a_profile_under_a_symlinked_parent_still_works(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    picture = still(256)
    home = write_face(tmp_path / "link", "coder", PHOTO, picture)
    assert avatars.face_for("coder", home).image == picture
    assert avatars._meta(home)["imageKind"] == "photo"


def test_a_picture_over_the_limit_falls_back_and_one_at_the_limit_does_not(tmp_path):
    at = still(256).ljust(256 * 1024, b"\0")
    assert avatars.face_for("a", write_face(tmp_path, "a", PHOTO, at)).image == at
    assert avatars.face_for("b", write_face(tmp_path, "b", PHOTO, at + b"\0")).image == DRAWN


def test_only_the_size_limit_of_bytes_is_read(tmp_path, monkeypatch):
    home = write_face(tmp_path, "coder", PHOTO, still(256).ljust(10 * 1024 * 1024, b"\0"))
    import builtins
    real, sizes = builtins.open, []

    class Spy:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def read(self, n=-1):
            sizes.append(n)
            return self.f.read(n)

    def spy_open(path, *a, **k):
        f = real(path, *a, **k)
        return Spy(f) if str(path).endswith("avatar.png") else f

    monkeypatch.setattr(builtins, "open", spy_open)
    avatars._picture(home)
    assert sizes == [256 * 1024 + 1]


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"<svg xmlns='x'/>", b"GIF89a....", b"RIFF1234WAVE"])
def test_what_is_not_a_picture_falls_back_to_the_drawn_face(tmp_path, data):
    assert avatars.face_for("coder", write_face(tmp_path, "coder", PHOTO, data)).image == DRAWN


@pytest.mark.parametrize("ext, data", [("png", b"\x89PNG\r\n\x1a\n" + bytes(40)), ("jpg", b"\xff\xd8\xff\xe0" + bytes(40)),
                                       ("webp", b"RIFF\0\0\0\0WEBP" + bytes(40))])
def test_each_kind_of_picture_is_taken_as_it_is(tmp_path, ext, data):
    f = avatars.face_for("coder", write_face(tmp_path, "coder", PHOTO, data, ext))
    assert (f.image, f.static) == (data, None)


@pytest.mark.parametrize("meta", [{"pet": "boba"}, {"shape": "sigil-3"}])
def test_a_bad_picture_for_a_face_only_desktop_can_draw_means_no_avatar(tmp_path, meta):
    assert avatars.face_for("coder", write_face(tmp_path, "coder", meta, b"not an image")) is None


# ------------------------------------------------------------------ colors


@pytest.mark.parametrize("color", ["#abc", "#abcd", "#aabbcc", "#aabbccdd", "hsl(285 68% 58%)", "hsl(240, 100%, 50%)",
                                   "rgb(1, 2, 3)", "rgba(232,220,195,0.95)", "rgb(255 0 0 / 50%)", "hsl(285deg 68% 58% / 0.5)",
                                   "rgb(-10, 0, 0)", "hsl(0 200% 50%)", "rgb(300, 0, 0)", "rgb(100%, 0%, 0%)"])
def test_every_accepted_color_draws_a_still(color):
    assert hermes_face.valid_color(color) == color
    assert hermes_face.static_png("circle", color, 16).startswith(b"\x89PNG")


@pytest.mark.parametrize("color", ["#12345", "#1234567", "#123456789", "rgb( )", "rgb(1..2, 0, 0)", "rgb(1, 2)", "rgb(1, 2, 3, 4, 5)",
                                   "rgb(1deg, 2, 3)", "hsl(10% 5% 5%)", "hsl(1 2deg 3%)", "rgb(1 2 3 / 1deg)", "rgb(- 1 2)"])
def test_a_color_that_cannot_be_parsed_falls_back_to_the_name(color):
    assert hermes_face.valid_color(color) is None
    assert hermes_face.appearance("coder", {"color": color})[1] == "hsl(285 68% 58%)"


@pytest.mark.parametrize("color, rgba", [("rgb(255 0 0 / 50%)", (1, 0, 0, 0.5)), ("rgb(-10, 300, 0)", (0, 1, 0, 1)),
                                         ("rgba(0, 0, 0, 7)", (0, 0, 0, 1)), ("rgb(0 0 0 / -1)", (0, 0, 0, 0)),
                                         ("hsl(0 200% 50%)", (1, 0, 0, 1)), ("hsl(0 100% 150%)", (1, 1, 1, 1)),
                                         ("rgb(100%, 0%, 50%)", (1, 0, 0.5, 1)), ("#ff000080", (1, 0, 0, 128 / 255))])
def test_channels_and_alpha_are_clamped(color, rgba):
    assert hermes_face._parse_rgba(color) == pytest.approx(rgba)


# ------------------------------------------------------------------ one bad profile


def test_a_profile_yaml_of_invalid_utf8_stops_only_itself(hermes):
    (hermes / "profiles" / "bencha" / "profile.yaml").write_bytes(b"display_name: \xff\xfe\n")
    assert {p.id for p in accounts.list_profiles()} == {"default", "coder", "bencha"}
    accounts.reconcile()
    assert accounts.token_for("coder")


@pytest.mark.parametrize("text", ["ui_meta: true\n  hermes-bots:\n    shape: pill\n",
                                  "ui_meta: x\n  hermes-bots: y\n    shape: pill\n",
                                  "previous_names: x\n- a\n- b\n"])
def test_the_reader_without_pyyaml_survives_a_strange_shape(tmp_path, monkeypatch, text):
    monkeypatch.setitem(sys.modules, "yaml", None)
    home = make_profile(tmp_path, "bot")
    (home / "profile.yaml").write_text(text)
    assert accounts.read_profile("bot", home).id == "bot"
    assert avatars._meta(home) == {}


# ------------------------------------------------------------------ work per pass


def test_a_pass_with_nothing_to_upload_draws_no_still(hermes, fake_api, monkeypatch):
    calls = []
    real = hermes_face.static_png
    monkeypatch.setattr(hermes_face, "static_png", lambda *a, **k: calls.append(a) or real(*a, **k))
    avatars.sync()
    assert len(calls) == 3  # one per upload
    calls.clear()
    avatars.sync()
    assert calls == []


def test_a_new_still_format_sends_every_face_again(hermes, fake_api, monkeypatch):
    avatars.sync()
    fake_api.calls.clear()
    monkeypatch.setattr(avatars, "_STILL_FORMAT", b"frame0-png-2")
    avatars.sync()
    assert len(puts(fake_api)) == 3


# ------------------------------------------------------------------ the source itself


def test_the_blobatar_port_has_no_invisible_characters_and_still_trims_them():
    import unicodedata
    source = (ROOT / "annotary_hermes" / "blobatar.py").read_text(encoding="utf-8")
    invisible = {c for c in source if ord(c) > 126 and unicodedata.category(c) in ("Zs", "Zl", "Zp", "Cf")}
    assert not invisible, sorted(hex(ord(c)) for c in invisible)
    for code in (0xa0, 0x1680, 0x2003, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff):
        assert blobatar._js_trim(f"{chr(code)}x{chr(code)}") == "x"
    assert blobatar._js_trim("\x1cx") == "\x1cx"  # Python's strip() would take it; JavaScript keeps it


def needs_avatars():
    """An empty upload changes nothing: any answer but 404 means the route is there."""
    try:
        server.api(server.owner_token(), "PUT", "/api/v1/me/avatar", {})
    except server.ServerError as e:
        assert getattr(e, "status", None) != 404, "the pinned Annotary must have Member avatars"


def member(handle):
    return next(m for m in server.api(server.owner_token(), "GET", "/api/v1/members")["members"] if m["handle"] == handle)


def test_the_real_server_takes_every_kind_of_face(hermes):
    needs_avatars()
    accounts.reconcile()
    tok = accounts.token_for("coder")
    for shape in SHAPES:
        svg = hermes_face.animated_svg(shape, "hsl(285 68% 58%)")
        avatars._upload(tok, avatars.Face(svg.encode(), lambda: hermes_face.static_png(shape, "hsl(285 68% 58%)")))
    m = member("coder")
    assert m["avatar"]["type"] == "image/svg+xml" and m["avatar"]["static_type"] == "image/png"
    for seed, kind in (("a", ""), ("b", "sun"), ("c", "cloud"), ("d", "triangle"), ("e", "capsule")):
        avatars._upload(tok, avatars.Face(blobatar.face(f"blobatar:{seed}:{kind}", "coder").svg(64).encode()))
    assert member("coder")["avatar"]["type"] == "image/svg+xml"


def test_a_reconcile_puts_each_face_on_the_real_server_and_follows_a_change(hermes):
    needs_avatars()
    assert "avatar" not in accounts.reconcile()["coder"]  # a success says nothing
    first = member("coder")["avatar"]
    assert first["static_type"] == "image/png"
    (hermes / "profiles" / "coder" / "profile.yaml").write_text(
        "ui_meta:\n  hermes-bots:\n    shape: pill\n    color: '#112233'\n")
    accounts.reconcile()
    second = member("coder")["avatar"]
    assert second["hash"] != first["hash"]
