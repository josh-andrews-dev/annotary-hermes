# This file is a Python port of the classic "math face" in Hermes Desktop's hermes-bots plugin
# (apps/desktop/src/plugins/hermes-bots/avatar.tsx: defaultShapeFor, botAppearance, isDarkColor,
# sampleFaceRing, projectFacePoint, facePose and BotFace's markup) and of
# apps/desktop/src/lib/profile-color.ts, which are under the MIT License:
#
#   Copyright (c) 2026 Nous Research
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

"""A Hermes Bot Mode classic face as a self-contained animated SVG, and frame 0 of it as a PNG.

Desktop repaints the SVG from a 15 fps script. An avatar has no script, so each periodic term of
the idle pose becomes its own CSS keyframe animation on a nested group; it plays in an ``<img>``
and stops under prefers-reduced-motion. Standard library only.

Everything here must stay inside Annotary's SVG allowlist (``SVG_ELEMENTS``, ``SVG_ATTRIBUTES``
and ``CSS_FUNCTIONS`` in its ``avatar.rs``): the server refuses a file at the first thing off it.
"""

from __future__ import annotations

import math
import re
import struct
import zlib

MATH_SHAPES = ("circle", "squircle", "pill", "triangle", "hexagon", "cloud", "drop")
PRIMARY_COLOR = "#8b5cf6"
CLOUD_PATH = "M11 32 a7.5 7.5 0 0 1 -1 -14.9 A9.5 9.5 0 0 1 29 12.5 A7 7 0 0 1 30 32 Z"

_COLOR = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
                    r"|hsla?\([0-9 .,%/deg-]{1,48}\)|rgba?\([0-9 .,%/-]{1,48}\)")
_NUMBER = re.compile(r"(-?(?:\d+\.?\d*|\.\d+))(%|deg)?")

# The idle pose's terms, facePose(): (amplitude, angular speed).
_TURN = (1.5, 0.5)
_TILT = (1.0, 0.27)
_ROLL = (1.2, 0.85)
_BLINK_PERIOD, _BLINK_AT = 3.2, 3.02
_EYE_RY = 2.3
_SAMPLES = 36


def _hash(text: str) -> int:
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def default_shape(name: str) -> str:
    return MATH_SHAPES[_hash(name) % len(MATH_SHAPES)]


def profile_color(name: str) -> str | None:
    key = name.strip()
    if not key or key == "default":
        return None
    return f"hsl({_hash(key) % 360} 68% 58%)"


def valid_color(color: object) -> str | None:
    """*color* if it is a CSS color of a form this file can draw, else None: it goes into the SVG."""
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        return None
    try:
        _parse_rgba(color)
    except ValueError:
        return None
    return color


def appearance(name: str, meta: dict | None) -> tuple[str, str]:
    """(shape, color) as Desktop's botAppearance picks them."""
    meta = meta or {}
    if name.strip().lower() == "default" and not meta.get("custom"):
        return "squircle", PRIMARY_COLOR
    shape = meta.get("shape") if isinstance(meta.get("shape"), str) else ""
    return shape or default_shape(name), valid_color(meta.get("color")) or profile_color(name) or PRIMARY_COLOR


def is_dark(color: str) -> bool:
    # Mirrors JS parseInt(hex.slice(1), 16): a non-hex color ("hsl(...)") parses as NaN, which
    # bit-shifts to 0, so Desktop treats every hsl() body as dark and gives it cream eyes.
    digits = ""
    for ch in color[1:]:
        if ch not in "0123456789abcdefABCDEF":
            break
        digits += ch
    n = int(digits, 16) if digits else 0
    r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 110


def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _drop_ring(steps: int) -> list[tuple[float, float]]:
    n = max(8, steps // 3)
    pts = [_cubic((20, 3), (20, 3), (6, 20), (6, 27), i / n) for i in range(n)]
    pts += [(20 - 14 * math.cos(i / n * math.pi), 27 + 13.5 * math.sin(i / n * math.pi)) for i in range(n + 1)]
    pts += [_cubic((34, 27), (34, 20), (20, 3), (20, 3), i / n) for i in range(1, n + 1)]
    return pts


def _arc(x1, y1, rx, ry, large, sweep, x2, y2):
    """svgArc(): the center form of an SVG elliptical arc, as (cx, cy, rx, ry, theta1, dtheta)."""
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    lam = dx * dx / (rx * rx) + dy * dy / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    den = rx * rx * dy * dy + ry * ry * dx * dx
    sq = math.sqrt(max(0, (rx * rx * ry * ry - rx * rx * dy * dy - ry * ry * dx * dx) / den))
    if large == sweep:
        sq = -sq
    cx = sq * (rx * dy / ry) + (x1 + x2) / 2
    cy = sq * (-ry * dx / rx) + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.acos(max(-1, min(1, (ux * vx + uy * vy) / ((math.hypot(ux, uy) * math.hypot(vx, vy)) or 1))))
        return -a if ux * vy - uy * vx < 0 else a

    ux, uy = (x1 - cx) / rx, (y1 - cy) / ry
    theta = ang(1, 0, ux, uy)
    delta = ang(ux, uy, (x2 - cx) / rx, (y2 - cy) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    if sweep and delta < 0:
        delta += 2 * math.pi
    return cx, cy, rx, ry, theta, delta


def _cloud_ring() -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for args, n in (((11, 32, 7.5, 7.5, 0, 1, 10, 17.1), 24), ((10, 17.1, 9.5, 9.5, 0, 1, 29, 12.5), 36),
                    ((29, 12.5, 7, 7, 0, 1, 30, 32), 24)):
        cx, cy, rx, ry, theta, delta = _arc(*args)
        pts += [(cx + rx * math.cos(theta + delta * i / n), cy + ry * math.sin(theta + delta * i / n))
                for i in range(n)]
    return pts + [(30 + (11 - 30) * i / 8, 32) for i in range(8)]


def face_ring(kind: str, steps: int = 52) -> list[tuple[float, float]]:
    """sampleFaceRing(): the outline of a face in the 40-unit face box."""
    if kind in ("drop", "teardrop"):
        return _drop_ring(steps)
    if kind == "cloud":
        return _cloud_ring()
    pts = []
    for i in range(steps):
        a = i / steps * math.pi * 2 - math.pi / 2
        c, s = math.cos(a), math.sin(a)
        rx = ry = 16.2
        if kind == "blob":
            rx = ry = 16 + 1.7 * math.sin(3 * a) + 0.7 * math.cos(5 * a)
        elif kind == "squircle":
            rx = ry = 16.2 / ((abs(c) ** 5 + abs(s) ** 5) ** (1 / 5) or 1)
        elif kind == "pill":
            rx = ry = 16 / ((abs(c) ** 8 + abs(s / 0.72) ** 8) ** (1 / 8) or 1)
        elif kind in ("triangle", "tetrahedron", "wedge"):
            u = (a + math.pi / 2 + math.pi * 2) % (math.pi * 2)
            sector = (u / (math.pi * 2 / 3)) % 1
            rx = ry = 13.5 / max(0.42, math.cos((sector - 0.5) * 1.9))
        elif kind in ("hexagon", "hex", "icosahedron", "dodecahedron"):
            seg = math.pi / 3
            rx = ry = 16.2 * math.cos(seg / 2) / math.cos(a - seg * _js_round(a / seg))
        elif kind in ("cube", "octahedron"):
            rx = ry = 16 / ((abs(c) ** 3.1 + abs(s) ** 3.1) ** (1 / 3.1) or 1)
        elif kind == "pebble":
            rx = 16.4 * (1.04 - 0.14 * math.cos(2 * a))
            ry = 15.2 * (1.06 + 0.08 * math.sin(2 * a))
        pts.append((20 + rx * c, 20 + ry * s))
    return pts


def _js_round(v: float) -> int:
    return math.floor(v + 0.5)  # Math.round: Python's round() takes halves to even


def _f(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".") or "0"


def _keyframes(name: str, period: float, fn) -> str:
    stops = "".join(f"{_f(i / _SAMPLES * 100)}%{{transform:{fn(i / _SAMPLES * period)}}}" for i in range(_SAMPLES + 1))
    return f"@keyframes {name}{{{stops}}}"


def _eye_colors(color: str) -> tuple[str, str]:
    return (("rgba(232,220,195,0.95)", "rgba(0,0,0,0.6)") if is_dark(color)
            else ("rgba(0,0,0,0.85)", "rgba(255,255,255,0.85)"))


def animated_svg(shape: str, color: str, size: int = 64) -> str:
    """The idle face. *color* must have passed :func:`valid_color`."""
    eye, hl = _eye_colors(color)
    ey = 22 if shape == "cloud" else 17.2
    css: list[str] = []
    anims: dict[str, tuple[str, str]] = {}

    def term(cls: str, origin: str, period: float, fn) -> None:
        css.append(_keyframes(f"{cls}k", period, fn))
        anims[cls] = (origin, f"{cls}k {_f(period)}s linear infinite")

    amp, w = _TILT
    term("t0", "20px 30.8px", 2 * math.pi / w, lambda t: f"rotate({_f(amp * math.sin(w * t))}deg)")
    body = f'<path fill="{color}" d="{CLOUD_PATH}"/>'
    if shape != "cloud":  # Desktop never re-projects the cloud body.
        d = "M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in face_ring(shape)) + "Z"
        body = f'<path fill="{color}" d="{d}"/>'
        ta, tw = _TURN
        term("sx", "20px 20px", 2 * math.pi / tw,
             lambda t: f"scale({_f(0.74 + 0.26 * abs(math.cos(math.radians(ta * math.sin(tw * t)))))},1)")
        term("sy", "20px 20px", 2 * math.pi / w,
             lambda t: f"scale(1,{_f(0.8 + 0.2 * abs(math.cos(math.radians(amp * math.sin(w * t)))))})")
        ra, rw = _ROLL
        term("ro", "20px 20px", 2 * math.pi / rw, lambda t: f"rotate({_f(ra * math.sin(rw * t))}deg)")
        body = f'<g class="sx"><g class="sy"><g class="ro">{body}</g></g></g>'
    cut = _f(_BLINK_AT / _BLINK_PERIOD * 100)
    after = _f(_BLINK_AT / _BLINK_PERIOD * 100 + 0.01)
    css.append(f"@keyframes bo{{0%,{cut}%{{opacity:1}}{after}%,100%{{opacity:0}}}}"
               f"@keyframes bs{{0%,{cut}%{{opacity:0}}{after}%,100%{{opacity:1}}}}")
    anims["bo"] = ("0 0", f"bo {_f(_BLINK_PERIOD)}s linear infinite")
    anims["bs"] = ("0 0", f"bs {_f(_BLINK_PERIOD)}s linear infinite")
    rules = "".join(f".{c}{{transform-box:view-box;transform-origin:{o};animation:{a}}}" for c, (o, a) in anims.items())
    style = rules + "".join(css) + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    eyes = (f'<g class="bo"><ellipse cx="15.4" cy="{ey}" rx="2.2" ry="{_EYE_RY}" fill="{eye}"/>'
            f'<ellipse cx="24.6" cy="{ey}" rx="2.2" ry="{_EYE_RY}" fill="{eye}"/>'
            f'<circle cx="14.8" cy="{_f(ey - 0.7)}" r="0.65" fill="{hl}"/>'
            f'<circle cx="24" cy="{_f(ey - 0.7)}" r="0.65" fill="{hl}"/></g>'
            f'<path class="bs" opacity="0" fill="none" stroke="{eye}" stroke-width="2" stroke-linecap="round" '
            f'd="M12.8 {ey} L18 {ey} M22 {ey} L27.2 {ey}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 44" width="{size}" height="{size}" '
            f'aria-hidden="true"><style>{style}</style><g class="t0">{body}{eyes}</g></svg>\n')


# ---- Frame 0 as a PNG ------------------------------------------------------------


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _parse_rgba(color: str) -> tuple[float, float, float, float]:
    """A CSS hex, rgb() or hsl() color as 0-1 channels, out-of-range values clamped as CSS does.
    Raises ValueError for anything else."""
    if color.startswith("#"):
        h = color[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        h = (h + "ff")[:8]
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4, 6))  # type: ignore[return-value]
    tokens = [t for t in re.split(r"[\s,/]+", color[color.index("(") + 1:-1]) if t]
    if len(tokens) not in (3, 4):
        raise ValueError(color)
    parts = []
    for token in tokens:
        m = _NUMBER.fullmatch(token)
        if not m:
            raise ValueError(color)
        parts.append((float(m[1]), m[2] or ""))
    alpha = 1.0
    if len(parts) == 4:
        value, unit = parts[3]
        if unit == "deg":
            raise ValueError(color)
        alpha = _clamp(value / 100 if unit == "%" else value)
    if color.startswith("rgb"):
        if any(unit == "deg" for _, unit in parts[:3]):
            raise ValueError(color)
        r, g, b = (_clamp(value / 100 if unit == "%" else value / 255) for value, unit in parts[:3])
        return r, g, b, alpha
    if parts[0][1] == "%" or parts[1][1] == "deg" or parts[2][1] == "deg":
        raise ValueError(color)
    h, s, li = parts[0][0] % 360, _clamp(parts[1][0] / 100), _clamp(parts[2][0] / 100)
    a = s * min(li, 1 - li)

    def channel(n: float) -> float:  # CSS Color 4, hslToRgb
        k = (n + h / 30) % 12
        return li - a * max(-1, min(k - 3, 9 - k, 1))

    return channel(0), channel(8), channel(4), alpha


def _fill(buf: list[list[float]], size: int, pts: list[tuple[float, float]], rgba) -> None:
    """Paint a polygon over *buf* (premultiplied RGBA rows), 4 sample lines per pixel."""
    ys = [p[1] for p in pts]
    edges = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    r, g, b, a = rgba
    for y in range(max(0, int(min(ys))), min(size, int(max(ys)) + 1)):
        cov = [0.0] * size
        for s in range(4):
            sy = y + (s + 0.5) / 4
            xs = sorted(x0 + (sy - y0) * (x1 - x0) / (y1 - y0)
                        for (x0, y0), (x1, y1) in edges if (y0 <= sy) != (y1 <= sy))
            for x0, x1 in zip(xs[::2], xs[1::2]):
                lo, hi = max(0.0, x0), min(float(size), x1)
                first, last = int(lo), min(size - 1, int(hi))
                for x in range(first, last + 1):
                    cov[x] += max(0.0, min(x + 1, hi) - max(x, lo)) / 4
        row = buf[y]
        for x, c in enumerate(cov):
            if c > 0:
                sa = min(1.0, c) * a
                i = x * 4
                row[i] = r * sa + row[i] * (1 - sa)
                row[i + 1] = g * sa + row[i + 1] * (1 - sa)
                row[i + 2] = b * sa + row[i + 2] * (1 - sa)
                row[i + 3] = sa + row[i + 3] * (1 - sa)


def _encode_png(buf: list[list[float]], size: int) -> bytes:
    raw = bytearray()
    for row in buf:
        raw.append(0)
        for x in range(size):
            i = x * 4
            a = row[i + 3]
            for c in range(3):
                raw.append(round(min(1.0, row[i + c] / a) * 255) if a else 0)
            raw.append(round(a * 255))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def static_png(shape: str, color: str, size: int = 160) -> bytes:
    """Frame 0 of :func:`animated_svg`: the pose at t=0 is the rest pose, eyes open."""
    scale = size / 44  # viewBox 40x44, centered in a square, as Desktop's own 160 px copy
    ox = (size - 40 * scale) / 2

    def at(pts):
        return [(ox + x * scale, y * scale) for x, y in pts]

    def oval(cx, cy, rx, ry):
        return [(cx + rx * math.cos(i * math.pi / 24), cy + ry * math.sin(i * math.pi / 24)) for i in range(48)]

    eye, hl = _eye_colors(color)
    ey = 22 if shape == "cloud" else 17.2
    buf = [[0.0] * (size * 4) for _ in range(size)]
    _fill(buf, size, at(face_ring(shape)), _parse_rgba(color))
    for pts, c in ((oval(15.4, ey, 2.2, _EYE_RY), eye), (oval(24.6, ey, 2.2, _EYE_RY), eye),
                   (oval(14.8, ey - 0.7, 0.65, 0.65), hl), (oval(24, ey - 0.7, 0.65, 0.65), hl)):
        _fill(buf, size, at(pts), _parse_rgba(c))
    return _encode_png(buf, size)
