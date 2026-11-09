# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render synthetic "phone photos" of receipts for end-to-end OCR tests."""

from __future__ import annotations

import io
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
]


def _font(size: int):
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def render_receipt(text: str, font_size: int = 26, width: int = 760) -> Image.Image:
    font = _font(font_size)
    lines = text.splitlines()
    line_h = int(font_size * 1.45)
    height = 60 + line_h * len(lines) + 60
    paper = Image.new("RGB", (width, height), (247, 246, 240))
    d = ImageDraw.Draw(paper)
    for i, ln in enumerate(lines):
        d.text((40, 50 + i * line_h), ln, fill=(25, 25, 30), font=font)
    return paper


def photo_of(paper: Image.Image, angle_deg: float = 4.0, perspective: float = 0.06, shadow: bool = True) -> bytes:
    """Place the paper on a dark wooden-ish background, tilt it, warp it, add a shadow. Returns JPEG bytes."""
    p = np.array(paper)
    ph, pw = p.shape[:2]
    bw, bh = int(pw * 1.6), int(ph * 1.35)
    rng = np.random.default_rng(42)
    bg = np.full((bh, bw, 3), (70, 52, 40), np.uint8)
    noise = rng.integers(-18, 18, size=(bh, bw, 1), dtype=np.int16)
    bg = np.clip(bg.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    cx, cy = bw / 2, bh / 2
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    a = math.radians(angle_deg)
    corners = []
    for x, y in src:
        x0, y0 = x - pw / 2, y - ph / 2
        corners.append([cx + x0 * math.cos(a) - y0 * math.sin(a), cy + x0 * math.sin(a) + y0 * math.cos(a)])
    dst = np.float32(corners)
    # Perspective: shrink the top edge a bit.
    dst[0][0] += pw * perspective
    dst[1][0] -= pw * perspective
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(p, m, (bw, bh))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), m, (bw, bh))
    out = bg.copy()
    out[mask > 0] = warped[mask > 0]
    if shadow:
        grad = np.linspace(0.65, 1.0, bw, dtype=np.float32)[None, :, None]
        out = np.clip(out.astype(np.float32) * grad, 0, 255).astype(np.uint8)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=88)
    return buf.getvalue()
