# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encrypted receipt repository.

Receipts are stored as opaque encrypted payloads, so filtering, search and
aggregation happen in memory after decrypting the current user's rows. A
personal archive holds hundreds to a few thousand documents, which this
handles comfortably.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Receipt, utcnow
from ..ocr.parser import format_cents
from ..security import crypto
from ..security.auth import Principal
from . import storage
from .domain import CATEGORIES, ReceiptData
from .profile import Profile


@dataclass
class ReceiptRecord:
    id: str
    created_at: datetime
    updated_at: datetime
    data: ReceiptData


def _aad(receipt_id: str, user_id: str) -> str:
    return f"receipt:{receipt_id}:{user_id}"


def _decode(p: Principal, row: Receipt) -> ReceiptRecord:
    payload = crypto.decrypt_json(p.dek, row.payload_blob, _aad(row.id, p.user.id))
    return ReceiptRecord(row.id, row.created_at, row.updated_at, ReceiptData.model_validate(payload))


def _encode(p: Principal, receipt_id: str, data: ReceiptData) -> bytes:
    return crypto.encrypt_json(p.dek, data.model_dump(mode="json"), _aad(receipt_id, p.user.id))


def list_all(db: Session, p: Principal) -> list[ReceiptRecord]:
    rows = db.scalars(select(Receipt).where(Receipt.user_id == p.user.id)).all()
    recs = [_decode(p, r) for r in rows]
    recs.sort(key=lambda r: (r.data.date.isoformat() if r.data.date else "0000", r.created_at), reverse=True)
    return recs


def get(db: Session, p: Principal, receipt_id: str) -> ReceiptRecord | None:
    row = db.get(Receipt, receipt_id) if receipt_id and receipt_id.isalnum() else None
    if row is None or row.user_id != p.user.id:
        return None
    return _decode(p, row)


def new_record_id() -> str:
    return crypto.new_id()


def insert(db: Session, p: Principal, data: ReceiptData, receipt_id: str | None = None, commit: bool = True) -> ReceiptRecord:
    rid = receipt_id or new_record_id()
    now = utcnow()
    db.add(Receipt(id=rid, user_id=p.user.id, created_at=now, updated_at=now, payload_blob=_encode(p, rid, data)))
    if commit:
        db.commit()
    return ReceiptRecord(rid, now, now, data)


def save(db: Session, p: Principal, rec: ReceiptRecord) -> ReceiptRecord:
    row = db.get(Receipt, rec.id)
    if row is None or row.user_id != p.user.id:
        raise KeyError(rec.id)
    rec.updated_at = utcnow()
    row.updated_at = rec.updated_at
    row.payload_blob = _encode(p, rec.id, rec.data)
    db.commit()
    return rec


def delete(db: Session, settings: Settings, p: Principal, receipt_id: str) -> bool:
    row = db.get(Receipt, receipt_id)
    if row is None or row.user_id != p.user.id:
        return False
    storage.delete_receipt_files(db, settings, p.user.id, receipt_id)
    db.delete(row)
    db.commit()
    return True


# --------------------------------------------------------------------------- querying


def available_years(records: list[ReceiptRecord]) -> list[int]:
    return sorted({r.data.tax_year for r in records if r.data.tax_year}, reverse=True)


def _haystack(r: ReceiptRecord, profile: Profile) -> str:
    d = r.data
    parts = [
        d.provider_name, d.provider_vat, d.provider_tax_code, d.document_number, d.description, d.notes,
        d.patient_tax_code, " ".join(d.tags), profile.beneficiary_label(d.beneficiary),
        CATEGORIES[d.category].label if d.category in CATEGORIES else None,
        format_cents(d.amount_cents), d.date.strftime("%d/%m/%Y") if d.date else None,
        d.original_filename, d.ocr.text if d.ocr else None,
    ]  # fmt: skip
    return " ".join(x for x in parts if x).lower()


def filter_records(
    records: list[ReceiptRecord],
    profile: Profile,
    *,
    year: int | None = None,
    category: str | None = None,
    status: str | None = None,
    beneficiary: str | None = None,
    q: str | None = None,
    evaluation: str | None = None,
    sort: str = "date_desc",
) -> list[ReceiptRecord]:
    from .tax import evaluate

    out = []
    terms = [t for t in (q or "").lower().split() if t]
    for r in records:
        d = r.data
        if year and d.tax_year != year:
            continue
        if category and d.category != category:
            continue
        if status and d.status != status:
            continue
        if beneficiary and d.beneficiary != beneficiary:
            continue
        if evaluation and evaluate(d, profile).status != evaluation:
            continue
        if terms:
            hay = _haystack(r, profile)
            if not all(t in hay for t in terms):
                continue
        out.append(r)
    if sort == "date_asc":
        out.sort(key=lambda r: (r.data.date.isoformat() if r.data.date else "9999", r.created_at))
    elif sort == "amount_desc":
        out.sort(key=lambda r: r.data.amount_cents or 0, reverse=True)
    elif sort == "amount_asc":
        out.sort(key=lambda r: r.data.amount_cents or 0)
    elif sort == "created_desc":
        out.sort(key=lambda r: r.created_at, reverse=True)
    return out


def find_duplicates(records: list[ReceiptRecord], target: ReceiptRecord) -> list[ReceiptRecord]:
    t = target.data
    dups = []
    for r in records:
        if r.id == target.id:
            continue
        d = r.data
        if t.image_sha256 and d.image_sha256 == t.image_sha256:
            dups.append(r)
            continue
        if t.date and t.amount_cents and d.date == t.date and d.amount_cents == t.amount_cents:
            same_issuer = (t.provider_vat and t.provider_vat == d.provider_vat) or (
                t.document_number and t.document_number == d.document_number
            )
            if same_issuer or not (t.provider_vat or d.provider_vat):
                dups.append(r)
    return dups
