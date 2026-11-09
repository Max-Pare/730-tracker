# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end OCR on synthetic phone photos (requires the tesseract binary + 'ita' data)."""

import io
import shutil

import numpy as np
import pytest
from PIL import Image

import receipt_samples as S
import synth
from app.ocr import engine, preprocess

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")

KNOWN = {"RSSMRA80A01H501U": "self"}


def _check_pharmacy(p):
    assert p.amount_cents == 2340
    assert p.date == "2025-03-09"
    assert p.provider_vat == "01234567897"
    assert p.patient_tax_code == "RSSMRA80A01H501U"
    assert p.payment_method == "tracciabile"
    assert p.category == "farmaci"


def test_tilted_perspective_photo():
    jpg = synth.photo_of(synth.render_receipt(S.PHARMACY_ELECTRONIC), angle_deg=6, perspective=0.07)
    out = engine.process_document(jpg, "ita+eng", KNOWN)
    _check_pharmacy(out.parsed)
    assert out.confidence > 0.7
    assert out.original_type == "image/jpeg" and out.scan_jpeg[:2] == b"\xff\xd8"


def test_sideways_photo_uses_osd():
    paper = synth.render_receipt(S.DOCTOR_INVOICE).rotate(90, expand=True)
    jpg = synth.photo_of(paper, angle_deg=2, perspective=0.03, shadow=False)
    out = engine.process_document(jpg, "ita+eng", {})
    assert out.parsed.amount_cents == 15200
    assert out.parsed.patient_tax_code == "BNCLRA85M41F205C"


def test_exif_and_gps_are_stripped():
    jpg = synth.photo_of(synth.render_receipt(S.PHARMACY_ELECTRONIC))
    im = Image.open(io.BytesIO(jpg))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif.tobytes())
    out = engine.process_document(buf.getvalue(), "ita+eng", KNOWN)
    assert not Image.open(io.BytesIO(out.original)).getexif()
    assert b"PhoneMaker" not in out.original


def _text_pdf(text: str) -> bytes:
    lines = text.splitlines()
    ops = ["BT", "/F1 10 Tf", "12 TL", "50 800 Td"]
    for ln in lines:
        esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc.encode('latin-1', 'replace').decode('latin-1')}) Tj T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def test_pdf_with_text_layer():
    out = engine.process_document(_text_pdf(S.LAB_ANALYSIS.replace("€", "EUR")), "ita+eng", {})
    assert out.engine == "pdf-text"
    assert out.original_type == "application/pdf"
    assert out.parsed.amount_cents == 1800
    assert out.parsed.category == "esami_analisi"
    assert out.scan_jpeg  # rendered preview


def test_scanned_pdf_goes_through_ocr():
    paper = synth.render_receipt(S.TICKET_ASL)
    buf = io.BytesIO()
    paper.save(buf, format="PDF", resolution=150)
    out = engine.process_document(buf.getvalue(), "ita+eng", KNOWN)
    assert out.engine == "pdf-ocr"
    assert out.parsed.amount_cents == 3615


def test_garbage_is_rejected():
    with pytest.raises(preprocess.ImageError):
        engine.process_document(b"not an image at all", "ita+eng", {})


def test_skew_estimate():
    gray = np.array(synth.render_receipt(S.PHARMACY_ELECTRONIC).convert("L"))
    for angle in (-9, -4, 5, 12):
        est = preprocess.estimate_skew(preprocess.rotate(gray, angle))
        assert abs(est + angle) < 0.6
