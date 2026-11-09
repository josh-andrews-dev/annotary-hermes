# Copyright 2026 Josh Andrews
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This file is a Python port of the face generator of blobatar 2.7.0
# (src/hash.ts, src/traits.ts, src/color.ts, src/shape.ts, src/render.ts,
# src/styles/blob.ts, src/styles/compose.ts, src/styles/shapes.ts), which is
# under the MIT License:
#
#   Copyright (c) 2026 Alain
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
#
# The recipe strings (`blobatar`, `blobatar:<seed>`, `blobatar:<seed>:<kind>`,
# `blobatar::<kind>`), BLOB_KINDS and BLOB_KIND_TRAIT follow Hermes Desktop's
# hermes-bots plugin (apps/desktop/src/plugins/hermes-bots/avatar.tsx), MIT,
# Copyright (c) 2026 Nous Research; both licenses are quoted in full in docs/THIRD_PARTY.md.

"""Hermes Desktop's blob faces, drawn the way its `blobatar` library draws
them: a seed picks a silhouette, its size and wobble, a color tone and two
capsule eyes, on a 100-unit view. `face(recipe, name)` gives the body, the
two eyes and the colors; `Face.svg()` gives the same markup the library
does, which is what the test vectors check (tests/fixtures/blobatar_vectors.json,
made by scripts/project/blobatar_vectors.mjs).

Static faces only: no expressions or motion. No Hermes imports.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

VERSION = "2.7.0"           # the blobatar release this port is checked against

BLOB_KINDS = ("round", "organic", "boxy", "capsule", "nub", "cloud", "droplet", "hexagon", "sun", "triangle")
# Trait positions at the center of each silhouette band (avatar.tsx).
BLOB_KIND_TRAIT = {
    "round": 0.11, "organic": 0.35, "boxy": 0.54, "capsule": 0.65, "nub": 0.745,
    "cloud": 0.825, "droplet": 0.8875, "hexagon": 0.9325, "sun": 0.965, "triangle": 0.99,
}

_M32 = 0xFFFFFFFF


# ---- Numbers as JavaScript prints them ----------------------------------------


def _js_round(v: float) -> float:
    """Math.round: halves go up."""
    return math.floor(v + 0.5)


def _r2(v: float) -> float:
    return _js_round(v * 100) / 100


def _num(v: float) -> str:
    """String(v) for the numbers a path holds."""
    if v == 0:
        return "0"
    if v == int(v) and abs(v) < 1e21:
        return str(int(v))
    return repr(v)


# ---- hash.ts ---------------------------------------------------------------------


def _imul(a: int, b: int) -> int:
    return (a * b) & _M32


def _feed(h: int, data: bytes) -> int:
    for byte in data:
        h = _imul(h ^ byte, 3432918353)
        h = ((h << 13) | (h >> 19)) & _M32
    return h


def _finalize(h: int) -> int:
    h = _imul(h ^ (h >> 16), 2246822507)
    h = _imul(h ^ (h >> 13), 3266489909)
    return (h ^ (h >> 16)) & _M32


def _js_trim(s: str) -> str:
    # String.prototype.trim: WhiteSpace and LineTerminator. Python's strip()
    # also takes U+001C..U+001F, which JavaScript keeps.
    ws = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
          "\u2028\u2029\u202f\u205f\u3000\ufeff")
    return s.strip(ws)


def normalize_seed(seed: str) -> str:
    return _js_trim(unicodedata.normalize("NFC", seed)).lower()


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def seed_state(seed: str, normalize: bool = True) -> int:
    s = normalize_seed(seed) if normalize else seed
    return _feed((1779033703 ^ _utf16_len(s)) & _M32, s.encode("utf-8", "surrogatepass"))


def stream(state: int, key: str) -> float:
    return _finalize(_feed(_feed(state, b"\xff"), key.encode("utf-8"))) / 4294967296


# ---- traits.ts -------------------------------------------------------------------


class Traits:
    def __init__(self, seed: str, normalize: bool = True, overrides: dict | None = None):
        self.state = seed_state(seed, normalize)
        self.overrides = overrides or {}

    def __call__(self, key: str) -> float:
        v = self.overrides.get(key)
        if isinstance(v, list):
            v = v[math.floor(stream(self.state, key) * len(v))] if v else None
        if v is None:
            return stream(self.state, key)
        if not v > 0:          # NaN falls to 0 as in JavaScript
            return 0.0
        return v if v < 1 else 0.999999

    def num(self, key: str, lo: float, hi: float) -> float:
        return lo + self(key) * (hi - lo)

    def int(self, key: str, lo: int, hi: int) -> int:
        return lo + math.floor(self(key) * (hi - lo + 1))

    def jitter(self, key: str, amount: float) -> float:
        return (self(key) * 2 - 1) * amount


# ---- color.ts --------------------------------------------------------------------


def _to_linear(l: float, c: float, h: float) -> list[float]:
    r = h * math.pi / 180
    a = c * math.cos(r)
    b = c * math.sin(r)
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.291485548 * b
    L, M, S = l_ * l_ * l_, m_ * m_ * m_, s_ * s_ * s_
    return [
        4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
        -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
        -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
    ]


def _in_gamut(rgb: list[float]) -> bool:
    return all(-1e-4 <= v <= 1 + 1e-4 for v in rgb)


def _resolve(col: tuple[float, float, float]) -> list[float]:
    l, c, h = col
    rgb = _to_linear(l, c, h)
    if not _in_gamut(rgb):
        lo, hi = 0.0, c
        for _ in range(12):
            mid = (lo + hi) / 2
            if _in_gamut(_to_linear(l, mid, h)):
                lo = mid
            else:
                hi = mid
        rgb = _to_linear(l, lo, h)
    return [min(1.0, max(0.0, v)) for v in rgb]


def _luminance(col) -> float:
    r, g, b = _resolve(col)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    x, y = _luminance(a), _luminance(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def ensure_contrast(fg, bg, minimum: float):
    if contrast(fg, bg) >= minimum:
        return fg
    lean = 1 if fg[0] >= bg[0] else -1
    for d in (lean, -lean):
        l, c, h = fg
        for _ in range(60):
            l = min(1.0, max(0.0, l + d * 0.02))
            if contrast((l, c, h), bg) >= minimum:
                return (l, c, h)
            if l == 0 or l == 1:
                break
    black, white = (0.0, 0.0, fg[2]), (1.0, 0.0, fg[2])
    return black if contrast(black, bg) >= contrast(white, bg) else white


def to_hex(col) -> str:
    out = "#"
    for v in _resolve(col):
        s = 12.92 * v if v <= 0.0031308 else 1.055 * math.pow(v, 1 / 2.4) - 0.055
        out += format(int(_js_round(s * 255)), "02x")
    return out


_TONES = (
    (0.2, (0.86, 0.085)),     # pastel
    (0.36, (0.9, 0.028)),     # pale neutral
    (0.62, (0.73, 0.135)),    # mid
    (0.8, (0.62, 0.165)),     # deep
    (0.93, (0.87, 0.16)),     # bright
    (1.0, (0.34, 0.035)),     # ink
)
TONE_NAMES = ("pastel", "pale", "mid", "deep", "bright", "ink")
_DARK_SURFACE = (0.145, 0.0, 0.0)
_SURFACE_FLOOR = 1.5


def tone_index(v: float) -> int:
    for i, (edge, _) in enumerate(_TONES):
        if v < edge:
            return i
    return 0


def palette(hue: float, enforce: bool = True, tone: float = 0) -> dict[str, str]:
    """{"bg", "head", "eye"} as `#rrggbb`, as color.ts's palette()."""
    tl, tc = _TONES[tone_index(tone)][1]
    head = ensure_contrast((tl, tc, hue), _DARK_SURFACE, _SURFACE_FLOOR)
    r = {
        "bg": (0.965, 0.01, hue),
        "head": head,
        "eye": (0.17, 0.02, hue) if head[0] >= 0.5 else (0.97, 0.012, hue),
    }
    if enforce:
        r["head"] = ensure_contrast(r["head"], r["bg"], 1.25)
        r["eye"] = ensure_contrast(r["eye"], r["head"], 4.5)
    return {k: to_hex(v) for k, v in r.items()}


# ---- Paths -----------------------------------------------------------------------
# A path is a list of commands, numbers already rounded to hundredths as the
# library prints them: ("M", x, y), ("L", x, y), ("H", x), ("V", y),
# ("Q", x1, y1, x, y), ("C", x1, y1, x2, y2, x, y), ("Z",).


def path_d(cmds: list[tuple]) -> str:
    out = ""
    for c in cmds:
        op, nums = c[0], c[1:]
        if op == "Z":
            out += "Z"
        elif op in ("H", "V"):
            out += op + _num(nums[0])
        else:
            pairs = [f"{_num(nums[i])} {_num(nums[i + 1])}" for i in range(0, len(nums), 2)]
            out += op + " ".join(pairs)
    return out


def superellipse(cx: float, cy: float, rx: float, ry: float, n: float = 4, rot: float = 0) -> list[tuple]:
    k = min(1, (8 * math.pow(2, -1 / n) - 4) / 3)
    a, b = rx, ry
    ak, bk = a * k, b * k
    pts = [(a, 0), (a, bk), (ak, b), (0, b), (-ak, b), (-a, bk), (-a, 0),
           (-a, -bk), (-ak, -b), (0, -b), (ak, -b), (a, -bk), (a, 0)]
    t = rot * math.pi / 180
    cos, sin = math.cos(t), math.sin(t)

    def at(i: int) -> tuple[float, float]:
        x, y = pts[i]
        return _r2(cx + x * cos - y * sin), _r2(cy + x * sin + y * cos)

    cmds = [("M", *at(0))]
    for i in range(1, 13, 3):
        cmds.append(("C", *at(i), *at(i + 1), *at(i + 2)))
    cmds.append(("Z",))
    return cmds


def blob_path(cx: float, cy: float, rx: float, ry: float, radii: list[float], rot: float = 0) -> list[tuple]:
    n = len(radii)
    t0 = rot * math.pi / 180
    p = []
    for i, m in enumerate(radii):
        a = t0 + 2 * math.pi * i / n
        p.append((cx + rx * m * math.cos(a), cy + ry * m * math.sin(a)))

    def at(i: int) -> tuple[float, float]:
        return p[((i % n) + n) % n]

    cmds = [("M", _r2(at(0)[0]), _r2(at(0)[1]))]
    for i in range(n):
        x0, y0 = at(i - 1)
        x1, y1 = at(i)
        x2, y2 = at(i + 1)
        x3, y3 = at(i + 2)
        cmds.append(("C", _r2(x1 + (x2 - x0) / 6), _r2(y1 + (y2 - y0) / 6),
                     _r2(x2 - (x3 - x1) / 6), _r2(y2 - (y3 - y1) / 6), _r2(x2), _r2(y2)))
    cmds.append(("Z",))
    return cmds


def polygon(cx: float, cy: float, rx: float, ry: float, sides: int, rnd: float = 0.3, rot: float = 0) -> list[tuple]:
    k = (rnd / 2 if rnd < 1 else 0.5) if rnd > 0 else 0
    t0 = rot * math.pi / 180 - math.pi / 2
    v = [(cx + rx * math.cos(t0 + 2 * math.pi * i / sides), cy + ry * math.sin(t0 + 2 * math.pi * i / sides))
         for i in range(sides)]

    def at(i: int) -> tuple[float, float]:
        return v[((i % sides) + sides) % sides]

    def cut(i: int, j: int) -> tuple[float, float]:
        (x0, y0), (x1, y1) = at(i), at(j)
        return _r2(x0 + (x1 - x0) * k), _r2(y0 + (y1 - y0) * k)

    cmds = [("M", *cut(0, -1))]
    for i in range(sides):
        x, y = at(i)
        cmds.append(("Q", _r2(x), _r2(y), *cut(i, i + 1)))
        if k < 0.5:
            cmds.append(("L", *cut(i + 1, i)))
    cmds.append(("Z",))
    return cmds


def box(cx: float, cy: float, rx: float, ry: float) -> list[tuple]:
    left, right = _r2(cx - rx), _r2(cx + rx)
    return [("M", left, _r2(cy - ry)), ("H", right), ("V", _r2(cy + ry)), ("H", left), ("Z",)]


def taper(cx: float, cy: float, rx: float, ry: float, tip: float) -> list[tuple]:
    t = max(1.05, tip)
    tx = rx * math.sqrt(1 - 1 / (t * t))
    ty = cy - ry / t
    apex = cy - t * ry
    px = tx * 0.14
    py = ty + 0.86 * (apex - ty)
    return [("M", _r2(cx - tx), _r2(ty)), ("L", _r2(cx - px), _r2(py)),
            ("Q", _r2(cx), _r2(apex), _r2(cx + px), _r2(py)), ("L", _r2(cx + tx), _r2(ty)), ("Z",)]


# ---- styles/shapes.ts and styles/compose.ts --------------------------------------


@dataclass
class _Body:
    cx: float
    cy: float
    rx: float
    ry: float
    n: float
    rot: float
    radii: list[float]
    sides: int = 0
    round: float = 0.3


_CORE = {"round": 1, "organic": 0.98, "boxy": 0.86, "capsule": 1.02, "nub": 0.88, "cloud": 0.78,
         "droplet": 0.78, "hexagon": 1.05, "sun": 0.7, "triangle": 1.15}
_BANDS = (("round", 0.22), ("organic", 0.48), ("boxy", 0.6), ("capsule", 0.7), ("nub", 0.79),
          ("cloud", 0.86), ("droplet", 0.915), ("hexagon", 0.95), ("sun", 0.98), ("triangle", 1))


def _pick_shape(v: float) -> str:
    for name, up_to in _BANDS:
        if v < up_to:
            return name
    return _BANDS[-1][0]


def _patch_body(shape: str, t: Traits, b: _Body) -> None:
    if shape == "boxy":
        b.n = t.num("body.n", 3.4, 6)
        b.rot = t.num("body.rot", -20, 20)
    elif shape == "capsule":
        b.ry *= t.num("capsule.squat", 0.55, 0.68)
    elif shape == "droplet":
        b.cy += 0.22 * b.ry
        b.n = 2
    elif shape == "hexagon":
        b.sides = 6
        b.rot = t.num("body.rot", -12, 12)
        b.round = t.num("poly.round", 0.24, 0.5)
    elif shape == "triangle":
        b.sides = 3
        b.rot = t.num("body.rot", -5, 5)
        b.round = t.num("poly.round", 0.24, 0.5)


def _face_region(shape: str, b: _Body) -> tuple[float, float, float, float]:
    def shrunk(k: float):
        return (b.cx, b.cy, b.rx * k, b.ry * k)

    if shape in ("organic", "cloud"):
        return shrunk(min(b.radii) * 0.95)
    if shape == "capsule":
        return shrunk(0.94)
    if shape == "droplet":
        return (b.cx, b.cy + b.ry * 0.05, b.rx * 0.88, b.ry * 0.88)
    if shape == "hexagon":
        return shrunk(0.84)
    if shape == "triangle":
        return (b.cx, b.cy + b.ry * 0.1, b.rx * 0.54, b.ry * 0.36)
    return (b.cx, b.cy, b.rx, b.ry)


def _decorate(shape: str, t: Traits, b: _Body) -> tuple[list[tuple[float, float, float]], list[list[tuple]]]:
    petals: list[tuple[float, float, float]] = []
    extra: list[list[tuple]] = []
    if shape == "capsule":
        for s in (-1, 1):
            petals.append((b.cx + s * (b.rx - b.ry), b.cy, b.ry))
    elif shape == "nub":
        for i in range(t.int("nub.n", 1, 2)):
            a = t.num(f"nub.a{i}", 0, 2 * math.pi)
            petals.append((b.cx + math.cos(a) * b.rx * 0.88, b.cy + math.sin(a) * b.rx * 0.88,
                           b.rx * t.num(f"nub.r{i}", 0.24, 0.4)))
    elif shape == "cloud":
        count = t.int("cloud.n", 4, 6)
        for i in range(count):
            a = math.pi + (math.pi * (i + 0.5)) / count
            petals.append((b.cx + math.cos(a) * b.rx * 0.8, b.cy + math.sin(a) * b.rx * 0.5,
                           b.rx * t.num(f"cloud.r{i}", 0.44, 0.62)))
    elif shape == "droplet":
        extra.append(taper(b.cx, b.cy, b.rx, b.ry, t.num("droplet.tip", 1.4, 1.65)))
    elif shape == "sun":
        count = t.int("sun.n", 6, 9)
        dist = b.rx * t.num("sun.dist", 1.0, 1.08)
        pr = b.rx * t.num("sun.r", 0.2, 0.26)
        off = t.num("sun.rot", 0, 2 * math.pi)
        for i in range(count):
            a = off + (2 * math.pi * i) / count
            petals.append((b.cx + math.cos(a) * dist, b.cy + math.sin(a) * dist, pr))
    return petals, extra


def _core_path(shape: str, b: _Body) -> list[tuple]:
    if shape in ("organic", "cloud"):
        return blob_path(b.cx, b.cy, b.rx, b.ry, b.radii, b.rot)
    if shape in ("hexagon", "triangle"):
        return polygon(b.cx, b.cy, b.rx, b.ry, b.sides, b.round, b.rot)
    if shape == "capsule":
        return box(b.cx, b.cy, b.rx - b.ry, b.ry)
    return superellipse(b.cx, b.cy, b.rx, b.ry, b.n, b.rot)


def _face_fit(t: Traits, b: _Body, face: tuple[float, float, float, float]) -> list[dict]:
    fcx, fcy, frx, fry = face
    rx = b.rx
    er0 = t.num("eye.rx", 0.075, 0.105) * rx
    ratio = t.num("eye.ratio", 1.9, 3.2)
    scale = t.num("eye.scale", 0.78, 1.24)
    stretch = t.num("eye.stretch", 0.85, 1.18)
    clearance = t.num("eye.gap", 0.1, 0.24) * rx
    wide = er0 * max(1, scale)
    tall = er0 * ratio * max(1, scale * stretch)
    gap0 = wide + rx * 0.03 + clearance

    gx = t.jitter("gaze.x", 0.09) * frx
    gy = t.num("gaze.y", -0.2, 0.08) * fry
    dy = t.jitter("eye.dy", 0.04) * fry
    reach = math.hypot(wide, tall)
    need = math.hypot((abs(gx) + gap0 + reach) / frx, (abs(gy) + abs(dy) + reach) / fry)
    fit = 0.9 / need if need > 0.9 else 1

    er = er0 * fit
    eye_ry = er * ratio
    gap = gap0 * fit
    room = max(0, min(1, clearance / tall))
    bound = min(12, math.asin(room) * 180 / math.pi)
    lean = t.num("eye.lean", -1, 1) * bound
    lean2 = max(-12, min(12, lean + t.jitter("eye.lean2", 3.5)))

    cx = fcx + gx * fit
    cy = fcy + gy * fit
    return [
        {"cx": cx - gap, "cy": cy, "rx": er, "ry": eye_ry, "n": t.num("eye.n", 3.5, 6), "rot": lean},
        {"cx": cx + gap, "cy": cy + dy * fit, "rx": er * scale, "ry": eye_ry * scale * stretch,
         "n": t.num("eye.n", 3.5, 6), "rot": lean2},
    ]


# ---- The face ---------------------------------------------------------------------


@dataclass
class Face:
    kind: str                                   # one of BLOB_KINDS
    tone: str                                   # one of TONE_NAMES
    head: str                                   # body color, #rrggbb
    eye: str                                    # eye color
    bg: str                                     # the library's backdrop color (unused: blob faces have none)
    petals: list[tuple[float, float, float]] = field(default_factory=list)   # circles, (cx, cy, r) rounded
    extra: list[list[tuple]] = field(default_factory=list)                   # extra outlines
    core: list[tuple] = field(default_factory=list)                          # the core outline
    eyes: list[list[tuple]] = field(default_factory=list)                    # the two eyes' outlines

    def svg(self, size: int | None = None) -> str:
        """The markup blobatar(seed, {size}) returns."""
        dim = f' width="{size}" height="{size}"' if size else ""
        body = (f'<g fill="{self.head}">'
                + "".join(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}"/>' for cx, cy, r in self.petals)
                + "".join(f'<path d="{path_d(p)}"/>' for p in self.extra)
                + f'<path d="{path_d(self.core)}"/>'
                + "</g>"
                + f'<g fill="{self.eye}">'
                + "".join(f'<path d="{path_d(e)}"/>' for e in self.eyes)
                + "</g>")
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"{dim}>{body}</svg>'


def generate(seed: str, traits: dict | None = None, normalize: bool = True) -> Face:
    """blobatar(seed, {traits}) as numbers."""
    t = Traits(seed, normalize, traits)
    tone = t("tone")
    pal = palette(t.num("hue", 0, 360), True, tone)

    shape = _pick_shape(t("shape"))
    r = t.num("body.r", 31, 38) * _CORE[shape]
    b = _Body(cx=50 + t.jitter("body.x", 1.5), cy=50 + t.jitter("body.y", 1.5), rx=r,
              ry=r * t.num("body.ratio", 0.92, 1.08), n=t.num("body.n", 1.9, 2.5), rot=0,
              radii=[1 + t.jitter(f"body.r{i}", 0.16) for i in range(t.int("body.pts", 6, 8))])
    _patch_body(shape, t, b)
    face_region = _face_region(shape, b)
    petals, extra = _decorate(shape, t, b)
    eyes = _face_fit(t, b, face_region)

    return Face(
        kind=shape, tone=TONE_NAMES[tone_index(tone)], head=pal["head"], eye=pal["eye"], bg=pal["bg"],
        petals=[(_r2(cx), _r2(cy), _r2(rr)) for cx, cy, rr in petals],
        extra=extra,
        core=_core_path(shape, b),
        eyes=[superellipse(e["cx"], e["cy"], e["rx"], e["ry"], e["n"], e["rot"]) for e in eyes],
    )


# ---- Hermes Desktop's recipe strings ---------------------------------------------


def is_recipe(shape) -> bool:
    return shape == "blobatar" or (isinstance(shape, str) and shape.startswith("blobatar:"))


def parse_recipe(shape: str | None, name: str | None) -> tuple[str, str]:
    """(seed, kind) as Hermes Desktop's parseBlobShape: the pinned seed, else
    the bot's name, which is the Hermes profile id (`RosterRow.name`), not
    its title or display name; kind is "" unless a known silhouette is pinned."""
    parts = shape.split(":") if isinstance(shape, str) else []
    seed_part = parts[1] if len(parts) > 1 else ""
    kind = parts[2] if len(parts) > 2 and parts[2] in BLOB_KINDS else ""
    return seed_part or name or "agent", kind


def face(recipe: str | None, name: str | None) -> Face:
    """The face Hermes Desktop draws for a `ui_meta.hermes-bots.shape` recipe
    on the profile `name`."""
    seed, kind = parse_recipe(recipe, name)
    return generate(seed, {"shape": BLOB_KIND_TRAIT[kind]} if kind else None)
