# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn an uploaded photo/PDF into an encrypted draft receipt."""

from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import utcnow
from ..ocr import engine, preprocess
from ..security import crypto
from ..security.auth import Principal
from . import receipts, storage
from .domain import OcrInfo, ReceiptData
from .profile import Profile

log = logging.getLogger(__name__)


class UploadError(ValueError):
    pass


def _ocr_info(outcome: engine.OcrOutcome) -> OcrInfo:
    pr = outcome.parsed
    return OcrInfo(
        text=outcome.text[:20000],
        confidence=outcome.confidence,
        engine=outcome.engine,
        field_confidence=pr.confidence,
        warnings=pr.warnings + outcome.notes,
        items=[i.__dict__ for i in pr.items][:60],
        processed_at=utcnow().isoformat(),
    )


def _safe_filename(name: str | None) -> str | None:
    if not name:
        return None
    name = re.sub(r"[\x00-\x1f/\\]", "_", name.rsplit("/", 1)[-1])
    return name[:120] or None


def ingest(db: Session, settings: Settings, p: Principal, profile: Profile, data: bytes, filename: str | None) -> receipts.ReceiptRecord:
    if not data:
        raise UploadError("File vuoto.")
    if len(data) > settings.max_upload_bytes:
        raise UploadError(f"File troppo grande (massimo {settings.max_upload_mb} MB).")

    known = profile.known_tax_codes()
    notes: list[str] = []
    try:
        outcome = engine.process_document(data, settings.ocr_lang, known, settings.tesseract_cmd or None)
    except preprocess.ImageError as exc:
        raise UploadError(str(exc)) from exc
    except engine.OcrUnavailable as exc:
        # Keep the document anyway; the user can fill the fields by hand.
        log.warning("OCR unavailable: %s", exc)
        outcome = None
        notes.append("OCR non disponibile sul server: compila i campi manualmente.")
    except Exception as exc:  # pragma: no cover - defensive: never lose an upload
        log.exception("OCR failed")
        outcome = None
        notes.append(f"Elaborazione OCR non riuscita ({type(exc).__name__}): compila i campi manualmente.")

    rid = receipts.new_record_id()
    rd = ReceiptData(status="bozza", source="ocr", image_sha256=crypto.sha256(data).hex(), original_filename=_safe_filename(filename))

    if outcome is not None:
        pr = outcome.parsed
        rd = rd.model_copy(
            update=dict(
                date=date.fromisoformat(pr.date) if pr.date else None,
                amount_cents=pr.amount_cents,
                deductible_cents=pr.deductible_cents,
                provider_name=pr.provider_name,
                provider_vat=pr.provider_vat,
                provider_tax_code=pr.provider_tax_code,
                document_number=pr.document_number,
                category=pr.category,
                payment_method=pr.payment_method,
                ssn_provider=pr.ssn_provider,
                beneficiary=pr.beneficiary or "self",
                patient_tax_code=pr.patient_tax_code,
                ocr=_ocr_info(outcome),
            )
        )
        original, original_type, scan = outcome.original, outcome.original_type, outcome.scan_jpeg
    else:
        if data[:5] == engine.PDF_MAGIC:
            original, original_type, scan = data, "application/pdf", None
        else:
            try:
                rgb = preprocess.load_image(data)
            except preprocess.ImageError as exc:
                raise UploadError(str(exc)) from exc
            original, original_type, scan = preprocess.encode_jpeg(rgb), "image/jpeg", None
        rd = rd.model_copy(update=dict(ocr=OcrInfo(warnings=notes, processed_at=utcnow().isoformat())))

    receipts.insert(db, p, ReceiptData(), receipt_id=rid, commit=False)
    db.flush()
    files = {"original": storage.put_file(db, settings, p, rid, original, original_type)}
    types = {"original": original_type}
    if scan:
        files["scan"] = storage.put_file(db, settings, p, rid, scan, "image/jpeg")
        types["scan"] = "image/jpeg"
    rd = rd.model_copy(update=dict(files=files, file_types=types))
    rec = receipts.ReceiptRecord(rid, utcnow(), utcnow(), rd)
    return receipts.save(db, p, rec)  # single commit: row + files + payload


def reprocess(db: Session, settings: Settings, p: Principal, profile: Profile, rec: receipts.ReceiptRecord) -> receipts.ReceiptRecord:
    """Run OCR again on the stored original and refresh only the OCR suggestions."""
    fid = rec.data.files.get("original")
    got = storage.get_file(db, settings, p, fid) if fid else None
    if not got:
        raise UploadError("Documento originale non disponibile.")
    content, _ = got
    try:
        outcome = engine.process_document(content, settings.ocr_lang, profile.known_tax_codes(), settings.tesseract_cmd or None)
    except (preprocess.ImageError, engine.OcrUnavailable) as exc:
        raise UploadError(str(exc)) from exc
    pr = outcome.parsed
    d = rec.data
    update = {
        "date": date.fromisoformat(pr.date) if pr.date else d.date,
        "amount_cents": pr.amount_cents if pr.amount_cents is not None else d.amount_cents,
        "deductible_cents": pr.deductible_cents,
        "provider_name": pr.provider_name or d.provider_name,
        "provider_vat": pr.provider_vat or d.provider_vat,
        "provider_tax_code": pr.provider_tax_code or d.provider_tax_code,
        "document_number": pr.document_number or d.document_number,
        "category": pr.category or d.category,
        "payment_method": pr.payment_method if pr.payment_method != "sconosciuto" else d.payment_method,
        "ssn_provider": pr.ssn_provider or d.ssn_provider,
        "patient_tax_code": pr.patient_tax_code or d.patient_tax_code,
        "beneficiary": pr.beneficiary or d.beneficiary,
        "status": "bozza",
        "ocr": _ocr_info(outcome),
    }
    if outcome.scan_jpeg:
        old_scan = d.files.get("scan")
        files = dict(d.files)
        files["scan"] = storage.put_file(db, settings, p, rec.id, outcome.scan_jpeg, "image/jpeg")
        types = dict(d.file_types, scan="image/jpeg")
        update.update(files=files, file_types=types)
        if old_scan:
            storage.delete_receipt_files(db, settings, p.user.id, rec.id, keep=set(files.values()))
    rec.data = d.model_copy(update=update)
    return receipts.save(db, p, rec)
