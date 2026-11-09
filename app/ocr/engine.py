# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR orchestration: images and PDFs in, parsed receipt + archive images out."""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from . import preprocess
from .parser import ParsedReceipt, parse_receipt_text

log = logging.getLogger(__name__)

# Tesseract's OpenMP threads contend badly when several OCR passes run at once
# (passes are parallelised here instead). Without this, two concurrent
# processes can be 50x slower.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

PDF_MAGIC = b"%PDF-"


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class OcrOutcome:
    text: str
    confidence: float  # 0..1 mean word confidence (1.0 for PDF text layers)
    parsed: ParsedReceipt
    scan_jpeg: bytes | None
    original: bytes
    original_type: str
    engine: str
    notes: list[str] = field(default_factory=list)


def _pytesseract(cmd: str | None = None):
    import pytesseract

    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def tesseract_available(cmd: str | None = None) -> bool:
    if cmd:
        return shutil.which(cmd) is not None or _exists(cmd)
    return shutil.which("tesseract") is not None


def _exists(path: str) -> bool:
    from pathlib import Path

    return Path(path).is_file()


def tesseract_version(cmd: str | None = None) -> str:
    try:
        return str(_pytesseract(cmd).get_tesseract_version())
    except Exception:  # pragma: no cover - environment dependent
        return "unavailable"


def detect_orientation(gray: np.ndarray, cmd: str | None = None) -> int:
    """Degrees (0/90/180/270) to rotate counter-clockwise so text is upright."""
    pt = _pytesseract(cmd)
    try:
        small, _ = preprocess._resize_max(gray, 1800)
        osd = pt.image_to_osd(small, config="--psm 0", output_type=pt.Output.DICT, timeout=30)
        rot = int(osd.get("rotate", 0))
        conf = float(osd.get("orientation_conf", 0))
        if rot and conf >= 1.5:
            # Tesseract reports the clockwise rotation needed.
            return (360 - rot) % 360
    except Exception as exc:  # OSD fails on sparse text; that's fine.
        log.debug("OSD failed: %s", exc)
    return 0


def ocr_array(img: np.ndarray, lang: str, psm: int, cmd: str | None = None) -> tuple[str, float]:
    """Run Tesseract and rebuild text line by line. Returns (text, mean confidence 0..1)."""
    pt = _pytesseract(cmd)
    data = pt.image_to_data(
        img,
        lang=lang,
        config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
        output_type=pt.Output.DICT,
        timeout=90,
    )
    lines: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        if not word or not word.strip():
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0:
            confs.append(conf)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((data["left"][i], word))
    out = []
    for key in sorted(lines, key=lambda k: (k[0], k[1], k[2])):
        words = sorted(lines[key])
        out.append(" ".join(w for _, w in words))
    mean = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return "\n".join(out), mean


def _score(text: str, conf: float, known: dict[str, str]) -> tuple[float, ParsedReceipt]:
    parsed = parse_receipt_text(text, known)
    return conf + 0.08 * parsed.found_fields() + (0.1 if parsed.amount_cents else 0), parsed


def ocr_image_bytes(data: bytes, lang: str, known: dict[str, str], cmd: str | None = None) -> OcrOutcome:
    if not tesseract_available(cmd):
        raise OcrUnavailable("Tesseract non è installato sul server.")
    prep = preprocess.prepare(data)
    gray, binary = prep.scan_gray, prep.binary
    rot = detect_orientation(gray, cmd)
    if rot:
        gray = preprocess.rotate_quadrant(gray, rot)
        binary = preprocess.rotate_quadrant(binary, rot)

    variants = [("gray-psm4", gray, 4), ("binary-psm4", binary, 4)]
    with ThreadPoolExecutor(max_workers=len(variants)) as pool:
        results = list(pool.map(lambda v: (v[0], *ocr_array(v[1], lang, v[2], cmd)), variants))

    best = None
    for name, text, conf in results:
        score, parsed = _score(text, conf, known)
        if best is None or score > best[0]:
            best = (score, name, text, conf, parsed)
    assert best is not None
    if best[4].found_fields() < 3:
        text, conf = ocr_array(gray, lang, 6, cmd)
        score, parsed = _score(text, conf, known)
        if score > best[0]:
            best = (score, "gray-psm6", text, conf, parsed)

    _, name, text, conf, parsed = best
    notes = []
    if not prep.document_found:
        notes.append("Bordo dello scontrino non rilevato: per risultati migliori fotografalo su uno sfondo scuro.")
    if conf < 0.55:
        notes.append("Qualità OCR bassa: controlla con attenzione i campi estratti.")
    return OcrOutcome(
        text=text,
        confidence=round(conf, 3),
        parsed=parsed,
        scan_jpeg=preprocess.encode_jpeg(gray, max_side=2200, quality=80),
        original=preprocess.encode_jpeg(prep.original_rgb, max_side=2400, quality=85),
        original_type="image/jpeg",
        engine=f"tesseract {tesseract_version(cmd)} ({name}, rot {rot}°, skew {prep.skew_angle:.1f}°)",
        notes=notes,
    )


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise preprocess.ImageError("PDF protetto da password.") from exc
    parts = []
    for page in reader.pages[:5]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _pdf_render(data: bytes, max_pages: int = 3) -> list[np.ndarray]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    pages = []
    try:
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            pil = page.render(scale=200 / 72).to_pil().convert("RGB")
            pages.append(np.array(pil))
            page.close()
    finally:
        pdf.close()
    return pages


def ocr_pdf_bytes(data: bytes, lang: str, known: dict[str, str], cmd: str | None = None) -> OcrOutcome:
    try:
        text = _pdf_text(data)
    except preprocess.ImageError:
        raise
    except Exception as exc:
        raise preprocess.ImageError("PDF non leggibile.") from exc
    try:
        pages = _pdf_render(data, max_pages=3)
    except Exception as exc:
        raise preprocess.ImageError("PDF non leggibile.") from exc
    preview = preprocess.encode_jpeg(pages[0], max_side=2200, quality=80) if pages else None

    if len(re.sub(r"\s", "", text)) >= 40:
        parsed = parse_receipt_text(text, known)
        return OcrOutcome(text, 1.0, parsed, preview, data, "application/pdf", "pdf-text", [])

    if not tesseract_available(cmd):
        raise OcrUnavailable("Tesseract non è installato sul server.")
    texts, confs = [], []
    for arr in pages:
        gray = preprocess.normalize_illumination(preprocess.cv2.cvtColor(arr, preprocess.cv2.COLOR_RGB2GRAY))
        t, c = ocr_array(gray, lang, 4, cmd)
        texts.append(t)
        confs.append(c)
    text = "\n".join(texts)
    conf = sum(confs) / len(confs) if confs else 0.0
    parsed = parse_receipt_text(text, known)
    return OcrOutcome(text, round(conf, 3), parsed, preview, data, "application/pdf", "pdf-ocr", [])


def process_document(data: bytes, lang: str, known: dict[str, str], cmd: str | None = None) -> OcrOutcome:
    """Entry point: dispatch on content (never trust the client-supplied type)."""
    if data[:5] == PDF_MAGIC:
        return ocr_pdf_bytes(data, lang, known, cmd)
    return ocr_image_bytes(data, lang, known, cmd)
