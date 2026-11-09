# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV and ZIP exports (for yourself or your commercialista / CAF)."""

from __future__ import annotations

import csv
import io
import re
import zipfile

from sqlalchemy.orm import Session

from ..config import Settings
from ..ocr.parser import format_cents
from ..security.auth import Principal
from . import storage
from .domain import CATEGORIES, PAYMENT_METHODS, STATUSES
from .profile import Profile
from .receipts import ReceiptRecord
from .tax import evaluate, summarize

COLUMNS = [
    "Data", "Anno", "Fornitore", "P.IVA fornitore", "CF fornitore", "N. documento", "Categoria",
    "Beneficiario", "CF destinatario", "Importo totale (€)", "Importo detraibile (€)", "Pagamento",
    "Struttura SSN/accreditata", "Esito", "Motivazione", "Stato", "Descrizione", "Note", "Etichette", "ID",
]  # fmt: skip

_EXT = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}


def _row(r: ReceiptRecord, profile: Profile) -> list[str]:
    d = r.data
    ev = evaluate(d, profile)
    return [
        d.date.strftime("%d/%m/%Y") if d.date else "",
        str(d.tax_year or ""),
        d.provider_name or "",
        d.provider_vat or "",
        d.provider_tax_code or "",
        d.document_number or "",
        CATEGORIES[d.category].label if d.category in CATEGORIES else "",
        profile.beneficiary_label(d.beneficiary),
        d.patient_tax_code or "",
        format_cents(d.amount_cents),
        format_cents(ev.eligible_cents) if ev.status == "detraibile" else "0,00",
        PAYMENT_METHODS.get(d.payment_method, ""),
        "sì" if d.ssn_provider else "no",
        ev.label,
        " ".join(ev.reasons),
        STATUSES.get(d.status, d.status),
        d.description or "",
        d.notes or "",
        ", ".join(d.tags),
        r.id,
    ]


def to_csv(records: list[ReceiptRecord], profile: Profile) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(COLUMNS)
    for r in records:
        w.writerow([_sanitize_cell(c) for c in _row(r, profile)])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel detects UTF-8


def _sanitize_cell(value: str) -> str:
    # Prevent spreadsheet formula injection from OCR'd or typed text.
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def _slug(s: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")
    return s[:40] or "documento"


def summary_text(records: list[ReceiptRecord], profile: Profile, year: int) -> str:
    s = summarize(records, profile, year)
    lines = [
        f"Riepilogo spese sanitarie {year} — {s.return_label}",
        "",
        f"Documenti: {s.receipts_count} (bozze escluse: {s.drafts_count})",
        f"Totale speso: € {format_cents(s.total_spent_cents)}",
        f"Spese sanitarie detraibili: € {format_cents(s.sanitarie_eligible_cents)}",
        f"  franchigia: € {format_cents(s.franchise_cents)} — base: € {format_cents(s.sanitarie_base_cents)}",
        f"  detrazione stimata 19%: € {format_cents(s.sanitarie_detraction_cents)}",
        f"Spese veterinarie detraibili: € {format_cents(s.vet_eligible_cents)} (max € 550)",
        f"  detrazione stimata 19%: € {format_cents(s.vet_detraction_cents)}",
        f"Detrazione totale stimata: € {format_cents(s.detraction_total_cents)}",
        f"Da verificare: € {format_cents(s.uncertain_cents)}  —  Non detraibili: € {format_cents(s.non_deductible_cents)}",
        "",
        "Stima indicativa: verifica sempre con il 730 precompilato e con il tuo CAF/commercialista.",
    ]
    if s.instalments_possible:
        lines.insert(-2, "Le spese superano € 15.493,71: è possibile rateizzare la detrazione in 4 anni.")
    return "\n".join(lines) + "\n"


def to_zip(db: Session, settings: Settings, p: Principal, records: list[ReceiptRecord], profile: Profile, year: int | None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("spese.csv", to_csv(records, profile))
        if year:
            zf.writestr("riepilogo.txt", summary_text(records, profile, year))
        for r in records:
            d = r.data
            base = f"{d.date.isoformat() if d.date else 'senza-data'}_{_slug(d.provider_name)}_{r.id[:8]}"
            for kind in ("original", "scan"):
                fid = d.files.get(kind)
                if not fid:
                    continue
                got = storage.get_file(db, settings, p, fid)
                if not got:
                    continue
                content, ctype = got
                suffix = "" if kind == "original" else "_scansione"
                zf.writestr(f"documenti/{base}{suffix}.{_EXT.get(ctype, 'bin')}", content)
    return buf.getvalue()
