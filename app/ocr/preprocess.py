# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenCV preprocessing: find the receipt in a phone photo and turn it into a clean "scan".

Pipeline: EXIF orientation -> document detection (edges/contours, with a
threshold-based fallback) -> perspective correction -> illumination
normalisation (removes shadows and thermal-paper gradients) -> denoise ->
deskew -> upscale small text. Produces a grey "scan" for the archive and
binarised variants for Tesseract.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 80_000_000  # ~80 MP: generous for phones, blocks decompression bombs


class ImageError(ValueError):
    pass


@dataclass
class Prepared:
    scan_gray: np.ndarray  # illumination-normalised grey, deskewed (archive + OCR)
    binary: np.ndarray  # adaptive-threshold variant for OCR
    original_rgb: np.ndarray  # EXIF-corrected original (for archive, re-encoded without metadata)
    document_found: bool
    skew_angle: float


def load_image(data: bytes) -> np.ndarray:
    """Decode bytes into an RGB array, applying EXIF orientation. Raises ImageError."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGBA") if "A" in im.getbands() else im.convert("RGB")
                if im.mode == "RGBA":
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.getchannel("A"))
                    im = bg
            if im.mode == "L":
                im = im.convert("RGB")
            arr = np.array(im)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError("Il file non è un'immagine valida o è danneggiato.") from exc
    if arr.ndim != 3 or min(arr.shape[:2]) < 50:
        raise ImageError("Immagine troppo piccola.")
    return arr


def _resize_max(img: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    scale = min(1.0, max_side / float(max(h, w)))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img, scale


def order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def four_point_transform(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = order_points(pts)
    width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], dtype="float32"), dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def find_document_quad(rgb: np.ndarray) -> np.ndarray | None:
    """Return the 4 corners of the receipt in ``rgb`` coordinates, or None."""
    small, scale = _resize_max(rgb, 1000)
    area_total = small.shape[0] * small.shape[1]
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    candidates: list[np.ndarray] = []
    # 1) Edge-based: works when the receipt contrasts with a textured background.
    edges = cv2.Canny(blur, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx) and cv2.contourArea(approx) > 0.15 * area_total:
            candidates.append(approx.reshape(4, 2))
            break

    # 2) Brightness-based: white paper on a darker surface.
    if not candidates:
        _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            c = max(contours, key=cv2.contourArea)
            a = cv2.contourArea(c)
            if 0.15 * area_total < a < 0.98 * area_total:
                peri = cv2.arcLength(c, True)
                approx = cv2.approxPolyDP(c, 0.02 * peri, True)
                if len(approx) == 4:
                    candidates.append(approx.reshape(4, 2))
                else:
                    candidates.append(cv2.boxPoints(cv2.minAreaRect(c)))

    if not candidates:
        return None
    return (candidates[0].astype("float32") / scale).astype("float32")


def normalize_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide by an estimate of the background to flatten shadows/gradients."""
    k = max(15, (min(gray.shape[:2]) // 25) | 1)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.medianBlur(bg, 21)
    norm = cv2.divide(gray, bg, scale=255)
    return cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)


def estimate_skew(gray: np.ndarray) -> float:
    """Weighted median angle of text lines, in degrees; ``rotate(img, angle)`` straightens the image."""
    inv = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    w = gray.shape[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 3))
    lines = cv2.dilate(inv, kernel, iterations=1)
    # RETR_LIST: the page outline may enclose everything; we want the inner text lines.
    contours, _ = cv2.findContours(lines, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    max_line_h = gray.shape[0] * 0.08
    angles: list[float] = []
    weights: list[float] = []
    for c in contours:
        (_, _), (rw, rh), ang = cv2.minAreaRect(c)
        if rw < rh:  # make ``ang`` the angle of the long side
            rw, rh = rh, rw
            ang += 90
        if rw < w * 0.15 or rh <= 0 or rh > max_line_h or rw / rh < 4:
            continue
        ang = ((ang + 45) % 90) - 45  # OpenCV's range differs between versions
        angles.append(ang)
        weights.append(rw)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    a = np.array(angles)[order]
    wts = np.array(weights)[order]
    cum = np.cumsum(wts)
    return float(a[np.searchsorted(cum, cum[-1] / 2)])


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    white = 255 if img.ndim == 2 else (255, 255, 255)
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=white)


def rotate_quadrant(img: np.ndarray, degrees: int) -> np.ndarray:
    degrees %= 360
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return img


def _scale_for_ocr(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape[:2]
    target_w = 1400
    if w < target_w:
        f = min(3.0, target_w / w)
        gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC)
    elif max(h, w) > 4000:
        gray, _ = _resize_max(gray, 4000)
    return gray


def binarize(gray: np.ndarray) -> np.ndarray:
    block = max(15, (min(gray.shape[:2]) // 40) | 1)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 12)


def prepare(data: bytes) -> Prepared:
    rgb = load_image(data)
    work, _ = _resize_max(rgb, 3200)
    quad = find_document_quad(work)
    if quad is not None:
        doc = four_point_transform(work, quad)
        # A "document" thinner than 1/12 of the photo is almost certainly a mis-detection.
        if min(doc.shape[:2]) < min(work.shape[:2]) / 12:
            doc, quad = work, None
    else:
        doc = work
    gray = cv2.cvtColor(doc, cv2.COLOR_RGB2GRAY)
    gray = normalize_illumination(gray)
    gray = cv2.fastNlMeansDenoising(gray, None, h=12, templateWindowSize=7, searchWindowSize=21)
    gray = _scale_for_ocr(gray)
    angle = estimate_skew(gray)
    if 0.3 < abs(angle) < 20:
        gray = rotate(gray, angle)
    return Prepared(
        scan_gray=gray,
        binary=binarize(gray),
        original_rgb=rgb,
        document_found=quad is not None,
        skew_angle=angle,
    )


def encode_jpeg(arr: np.ndarray, max_side: int = 2400, quality: int = 85) -> bytes:
    """Re-encode (drops all EXIF/GPS metadata)."""
    arr, _ = _resize_max(arr, max_side)
    im = Image.fromarray(arr)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
