# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain vocabulary and the receipt data schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..ocr.validators import is_valid_cf, is_valid_piva


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    group: str | None  # "sanitarie" | "veterinarie" | None (non detraibile)
    trace_exempt: bool  # payment traceability not required (art. 1 c. 680 L. 160/2019)
    hint: str


CATEGORIES: dict[str, Category] = {
    c.code: c
    for c in [
        Category("farmaci", "Farmaci e medicinali", "sanitarie", True, "Anche omeopatici e da banco (SOP/OTC), con scontrino parlante."),
        Category("dispositivi_medici", "Dispositivi medici", "sanitarie", True, "Con marcatura CE (es. misuratori, test, ausili)."),
        Category("occhiali_lenti", "Occhiali e lenti", "sanitarie", True, "Occhiali da vista e lenti a contatto sono dispositivi medici."),
        Category("ticket_ssn", "Ticket SSN", "sanitarie", True, "Compartecipazione alla spesa presso strutture pubbliche."),
        Category("visite_specialistiche", "Visite mediche e specialistiche", "sanitarie", False, ""),
        Category("esami_analisi", "Esami, analisi e diagnostica", "sanitarie", False, ""),
        Category("cure_dentistiche", "Cure dentistiche", "sanitarie", False, ""),
        Category("prestazioni_sanitarie", "Altre prestazioni sanitarie", "sanitarie", False, "Fisioterapia, psicologo, logopedista, infermiere…"),
        Category("ricoveri_interventi", "Ricoveri e interventi", "sanitarie", False, ""),
        Category("veterinarie_farmaci", "Veterinarie – farmaci", "veterinarie", True, ""),
        Category("veterinarie_prestazioni", "Veterinarie – visite e prestazioni", "veterinarie", False, ""),
        Category("non_detraibile", "Non detraibile", None, True, "Parafarmaci, cosmetici, integratori…"),
    ]
}  # fmt: skip

PAYMENT_METHODS: dict[str, str] = {
    "tracciabile": "Tracciabile (carta, bancomat, bonifico…)",
    "contanti": "Contanti",
    "sconosciuto": "Non indicato",
}

STATUSES: dict[str, str] = {
    "bozza": "Bozza da rivedere",
    "da_verificare": "Da verificare",
    "verificato": "Verificato",
}

RELATIONS: dict[str, str] = {
    "coniuge": "Coniuge",
    "figlio": "Figlio/a",
    "genitore": "Genitore",
    "altro": "Altro familiare",
}

StatusT = Literal["bozza", "da_verificare", "verificato"]
PaymentT = Literal["tracciabile", "contanti", "sconosciuto"]

MAX_AMOUNT_CENTS = 100_000_000  # € 1.000.000


def _clean_str(v, max_len: int):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:max_len] or None


class OcrInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    confidence: float = 0.0
    engine: str = ""
    field_confidence: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    processed_at: str | None = None


class ReceiptFields(BaseModel):
    """Fields the user can edit (web form and API share this)."""

    model_config = ConfigDict(extra="ignore")

    status: StatusT = "da_verificare"
    date: dt.date | None = None
    amount_cents: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_CENTS)
    deductible_cents: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_CENTS)
    provider_name: str | None = None
    provider_vat: str | None = None
    provider_tax_code: str | None = None
    document_number: str | None = None
    category: str | None = None
    payment_method: PaymentT = "sconosciuto"
    ssn_provider: bool = False
    beneficiary: str = "self"
    patient_tax_code: str | None = None
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("provider_name", mode="before")
    @classmethod
    def _v_provider(cls, v):
        return _clean_str(v, 120)

    @field_validator("document_number", mode="before")
    @classmethod
    def _v_docnum(cls, v):
        return _clean_str(v, 40)

    @field_validator("description", mode="before")
    @classmethod
    def _v_desc(cls, v):
        return _clean_str(v, 500)

    @field_validator("notes", mode="before")
    @classmethod
    def _v_notes(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s[:2000] or None

    @field_validator("provider_vat", mode="before")
    @classmethod
    def _v_vat(cls, v):
        s = _clean_str(v, 20)
        return s.upper().replace(" ", "") if s else None

    @field_validator("provider_tax_code", "patient_tax_code", mode="before")
    @classmethod
    def _v_cf(cls, v):
        s = _clean_str(v, 20)
        return s.upper().replace(" ", "") if s else None

    @field_validator("category", mode="before")
    @classmethod
    def _v_cat(cls, v):
        if v in (None, ""):
            return None
        if v not in CATEGORIES:
            raise ValueError("categoria non valida")
        return v

    @field_validator("beneficiary", mode="before")
    @classmethod
    def _v_benef(cls, v):
        s = _clean_str(v, 40)
        return s or "self"

    @field_validator("tags", mode="before")
    @classmethod
    def _v_tags(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = v.split(",")
        out: list[str] = []
        for t in v:
            t = _clean_str(t, 30)
            if t and t.lower() not in (x.lower() for x in out):
                out.append(t)
        return out[:15]

    def field_warnings(self) -> list[str]:
        w = []
        if self.provider_vat and not is_valid_piva(self.provider_vat.removeprefix("IT")):
            w.append("La partita IVA del fornitore non supera il controllo di validità.")
        if self.patient_tax_code and not is_valid_cf(self.patient_tax_code):
            w.append("Il codice fiscale del destinatario non è valido.")
        if self.deductible_cents is not None and self.amount_cents is not None and self.deductible_cents > self.amount_cents:
            w.append("L'importo detraibile supera il totale del documento.")
        return w


class ReceiptData(ReceiptFields):
    """Full encrypted payload of a receipt."""

    status: StatusT = "bozza"
    source: Literal["ocr", "manuale"] = "manuale"
    image_sha256: str | None = None
    files: dict[str, str] = Field(default_factory=dict)  # kind ("original"|"scan") -> StoredFile.id
    file_types: dict[str, str] = Field(default_factory=dict)  # kind -> MIME type
    original_filename: str | None = None
    ocr: OcrInfo | None = None

    @property
    def tax_year(self) -> int | None:
        return self.date.year if self.date else None

    @property
    def effective_deductible_cents(self) -> int | None:
        if self.amount_cents is None:
            return None
        if self.deductible_cents is None:
            return self.amount_cents
        return min(self.deductible_cents, self.amount_cents)

    def apply(self, fields: ReceiptFields) -> ReceiptData:
        return self.model_copy(update=fields.model_dump())


EDITABLE_FIELDS = tuple(ReceiptFields.model_fields)
