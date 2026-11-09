# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extract 730-relevant fields from the OCR text of an Italian medical receipt.

The parser is deliberately heuristic and conservative: every field carries a
confidence in [0, 1] so the UI can ask the user to double-check weak guesses.
It understands the common layouts:

* "documento commerciale" / scontrino parlante from pharmacies,
* invoices/receipts from doctors, dentists, labs, opticians,
* ticket payments to public health structures (ASL/ASST/AUSL/ULSS).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from . import validators

# --------------------------------------------------------------------------- helpers

_MONTHS = {
    "GEN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAG": 5, "GIU": 6,
    "LUG": 7, "AGO": 8, "SET": 9, "OTT": 10, "NOV": 11, "DIC": 12,
}  # fmt: skip

AMOUNT_RE = re.compile(r"(?<![\d.,/])(\d{1,3}(?:[.'’]\d{3})+|\d{1,6})\s?[,.]\s?(\d{2})(?![\d%/])(?!\s?%)")
DATE_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]\s?(\d{4}|\d{2})(?!\d)")
DATE_ISO_RE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)")
DATE_TXT_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:°|º)?\s+(GEN|FEB|MAR|APR|MAG|GIU|LUG|AGO|SET|OTT|NOV|DIC)[A-Z]*\.?\s+(\d{4})(?!\d)"
)
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?![\d,])")


_DIGITISH = r"[\d/.,:\-]"


def _fix_digits(line: str) -> str:
    """Repair letters misread inside numbers ("1O/12/2025" -> "10/12/2025", "l2,50" -> "12,50")."""
    s = re.sub(rf"(?<={_DIGITISH})[Oo](?={_DIGITISH})|(?<=\d)[Oo]\b|\b[Oo](?=\d)", "0", line)
    s = re.sub(rf"(?<={_DIGITISH})[lI|](?={_DIGITISH})|(?<=\d)[lI|]\b|\b[lI|](?=\d)", "1", s)
    return s


def _kw(line: str) -> str:
    """Uppercase line with common OCR digit/letter swaps fixed inside words."""
    s = line.upper()
    s = re.sub(r"(?<=[A-Z])0|0(?=[A-Z]{2})", "O", s)
    s = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", s)
    s = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", s)
    return s


def cents_from_match(m: re.Match) -> int:
    whole = re.sub(r"[.'’]", "", m.group(1))
    return int(whole) * 100 + int(m.group(2))


def _strip_dates(line: str) -> str:
    line = DATE_ISO_RE.sub(" ", line)
    line = DATE_NUM_RE.sub(" ", line)
    line = TIME_RE.sub(" ", line)
    return line


def amounts_in(line: str) -> list[int]:
    cleaned = _strip_dates(_fix_digits(line))
    # Percentages ("IVA 10,00%") are not amounts.
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s?%", " ", cleaned)
    return [cents_from_match(m) for m in AMOUNT_RE.finditer(cleaned)]


def format_cents(cents: int | None) -> str:
    if cents is None:
        return ""
    euros, c = divmod(abs(cents), 100)
    s = f"{euros:,}".replace(",", ".")
    return f"{'-' if cents < 0 else ''}{s},{c:02d}"


def parse_amount_input(value: str | None) -> int | None:
    """Parse a user-typed amount ("12,50", "1.234,56", "12.5", "€ 7") into cents."""
    if value is None:
        return None
    s = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        whole, _, frac = s.partition(".")
        if len(frac) == 3:  # "1.234" = thousands separator
            s = whole + frac
    try:
        from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

        cents = int((Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Importo non valido: {value!r}") from None
    return -cents if neg else cents


# --------------------------------------------------------------------------- result


@dataclass
class LineItem:
    description: str
    amount_cents: int
    deductible: bool | None  # None = neutral/unknown


@dataclass
class ParsedReceipt:
    date: str | None = None  # ISO yyyy-mm-dd
    amount_cents: int | None = None
    deductible_cents: int | None = None
    provider_name: str | None = None
    provider_vat: str | None = None
    provider_tax_code: str | None = None
    patient_tax_code: str | None = None
    beneficiary: str | None = None
    document_number: str | None = None
    payment_method: str = "sconosciuto"
    category: str | None = None
    ssn_provider: bool = False
    items: list[LineItem] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def found_fields(self) -> int:
        keys = ("date", "amount_cents", "provider_name", "provider_vat", "patient_tax_code", "category")
        return sum(1 for k in keys if getattr(self, k))


# --------------------------------------------------------------------------- dates


def _mk_date(d: int, m: int, y: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _date_candidates(line: str) -> list[date]:
    out: list[date] = []
    up = _fix_digits(line).upper()
    for m in DATE_ISO_RE.finditer(up):
        dt = _mk_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if dt:
            out.append(dt)
    for m in DATE_NUM_RE.finditer(up):
        dt = _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            out.append(dt)
    for m in DATE_TXT_RE.finditer(up):
        dt = _mk_date(int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))
        if dt:
            out.append(dt)
    return out


def extract_date(lines: list[str], today: date) -> tuple[date | None, float]:
    best: tuple[float, date] | None = None
    for i, line in enumerate(lines):
        kw = _kw(line)
        for dt in _date_candidates(line):
            if dt.year < 2000 or dt > today + timedelta(days=1):
                continue
            score = 0.5
            if re.search(r"\bDATA\b|\bDEL\b|EMISSIONE|EMESS|\bIL\b", kw):
                score += 0.25
            if TIME_RE.search(_strip_dates_only(_fix_digits(line))):
                score += 0.15
            if re.search(r"NAT[OA]\b|NASCITA|SCAD|VALID|NATO IL|NATA IL", kw):
                score -= 1.0
            if (today - dt).days > 3 * 366:
                score -= 0.3
            cand = (score, dt)
            if best is None or cand > best:
                best = cand
    if best is None or best[0] <= 0:
        return None, 0.0
    return best[1], min(0.95, best[0] + 0.1)


def _strip_dates_only(line: str) -> str:
    return DATE_NUM_RE.sub(" ", DATE_ISO_RE.sub(" ", line))


# --------------------------------------------------------------------------- totals

_TOTAL_STRONG = [
    (r"TOTALE\s+COMPLESSIVO", 1.0),
    (r"IMPORTO\s+PAGATO", 0.95),
    (r"TOTALE\s+(?:DOCUMENTO|FATTURA|RICEVUTA|DA\s+PAGARE|A\s+PAGARE|DOVUTO)", 0.95),
    (r"NETTO\s+A\s+PAGARE", 0.95),
    (r"IMPORTO\s+TOTALE", 0.9),
    (r"TOTALE\s+(?:EURO|EUR|€)", 0.9),
    (r"\bTOTALE\b", 0.8),
    (r"\bTOT[AE]?L?[EF]?\b\.?", 0.6),
    (r"\bIMPORTO\b", 0.45),
    (r"\bEURO\b", 0.3),
]
_TOTAL_EXCLUDE = re.compile(
    r"SUB\s*-?\s*TOTALE|SUBTOT|DI\s+CUI|\bIVA\b|IMPONIBILE|RESTO|SCONTO|ABBUONO|NON\s+RISCOSS|"
    r"PAGAMENTO\s+CONTANT|CONTANTI|PAGAMENTO\s+ELETTRONIC|ARROTONDAMENT|PUNTI|BOLLO|RITENUTA|ACCONTO|"
    r"TOTALE\s+PEZZI|N\.?\s*PEZZI|ARTICOLI"
)


def extract_total(lines: list[str]) -> tuple[int | None, float, int | None]:
    """Return (cents, confidence, line index)."""
    best: tuple[float, int, int] | None = None  # (score, cents, idx)
    for i, line in enumerate(lines):
        kw = _kw(line)
        if _TOTAL_EXCLUDE.search(kw):
            continue
        weight = 0.0
        for pattern, w in _TOTAL_STRONG:
            if re.search(pattern, kw):
                weight = w
                break
        if not weight:
            continue
        values = amounts_in(line)
        if not values and i + 1 < len(lines):
            nxt = lines[i + 1]
            if not _TOTAL_EXCLUDE.search(_kw(nxt)):
                values = amounts_in(nxt)
                weight -= 0.05
        if not values:
            continue
        cents = values[-1]
        if cents <= 0:
            continue
        cand = (weight, cents, i)
        if best is None or (cand[0], cand[1]) > (best[0], best[1]):
            best = cand
    if best:
        return best[1], min(0.95, best[0]), best[2]

    # Fallback: largest amount on the document, excluding obvious non-totals.
    pool: list[int] = []
    for line in lines:
        if _TOTAL_EXCLUDE.search(_kw(line)):
            continue
        pool.extend(v for v in amounts_in(line) if v > 0)
    if pool:
        return max(pool), 0.3, None
    return None, 0.0, None


# --------------------------------------------------------------------------- payment

_CASH = re.compile(r"CONTANT[EI]|\bCASH\b|\bRESTO\b")
_TRACE = re.compile(
    r"ELETTRONIC|BANCOMAT|PAGOBANCOMAT|\bCARTA\b|\bCARD\b|\bPOS\b|\bVISA\b|MASTERCARD|MAESTRO|\bAMEX\b|"
    r"AMERICAN\s+EXPRESS|BONIFICO|SATISPAY|PAYPAL|ASSEGNO|APPLE\s*PAY|GOOGLE\s*PAY|TRACCIABIL|"
    r"MONETA\s+ELETTRONICA|CONTACTLESS|\bSEPA\b|\bIBAN\b|DEBITO|CREDITO"
)


def extract_payment(lines: list[str]) -> tuple[str, float]:
    cash_amounts: list[int | None] = []
    trace_amounts: list[int | None] = []
    for line in lines:
        kw = _kw(line)
        vals = amounts_in(line)
        amount = vals[-1] if vals else None
        if _CASH.search(kw):
            if "RESTO" in kw:
                cash_amounts.append(amount if amount else 1)
            else:
                cash_amounts.append(amount)
        if _TRACE.search(kw) and not re.search(r"CREDITO\s+D.?IMPOSTA|NOTA\s+DI\s+CREDITO", kw):
            trace_amounts.append(amount)
    cash_pos = any(a for a in cash_amounts if a)
    trace_pos = any(a for a in trace_amounts if a)
    if trace_pos and not cash_pos:
        return "tracciabile", 0.9
    if cash_pos and not trace_pos:
        return "contanti", 0.9
    if trace_pos and cash_pos:
        return "sconosciuto", 0.3  # mixed payment
    if trace_amounts and not cash_amounts:
        return "tracciabile", 0.7
    if cash_amounts and not trace_amounts:
        return "contanti", 0.6
    return "sconosciuto", 0.0


# --------------------------------------------------------------------------- category

CATEGORY_KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "farmaci": [
        (r"\bFARMACIA\b", 2.5), (r"FARMAC[OI]\b", 2), (r"MEDICINAL", 2), (r"\bSOP\b", 1.5), (r"\bOTC\b", 1.5),
        (r"OMEOPAT", 1), (r"GALENIC", 1.5), (r"RICETTA", 0.5), (r"\bAIC\b", 1), (r"SCONTRINO\s+PARLANTE", 1),
    ],
    "dispositivi_medici": [
        (r"DISPOSITIV[OI]\s+MEDIC", 3), (r"DISP\.?\s*MED", 2.5), (r"SANITARIA\b", 1.5), (r"ORTOPEDI", 1.5),
        (r"APPARECCH\w*\s+ACUSTIC", 3), (r"MISURATORE", 1.5), (r"MARCHI[OA]\s+CE", 1.5), (r"PRESIDI", 1),
        (r"PLANTAR", 2), (r"AUSILI", 1.5),
    ],
    "occhiali_lenti": [
        (r"OTTIC[AO]\b", 3), (r"OCCHIAL", 3), (r"LENTI\b", 2), (r"LENTI\s+A\s+CONTATTO", 3), (r"MONTATURA", 2),
        (r"OPTOMETR", 2),
    ],
    "ticket_ssn": [
        (r"\bTICKET\b", 3), (r"\bA\.?S\.?L\.?\b", 2), (r"\bASST\b", 2.5), (r"\bAUSL\b", 2.5), (r"\bULSS\b", 2.5),
        (r"\bUSL\b", 2), (r"AZIENDA\s+(?:SANITARIA|OSPEDALIER|SOCIO)", 2.5), (r"SERVIZIO\s+SANITARIO", 2),
        (r"\bS\.?S\.?N\.?\b", 1.5), (r"\bCUP\b", 1), (r"PRONTO\s+SOCCORSO", 2), (r"PAGOPA", 1.5),
        (r"COMPARTECIPAZIONE", 2.5),
    ],
    "visite_specialistiche": [
        (r"\bVISITA\b", 2.5), (r"SPECIALISTIC", 2), (r"\bDOTT\.?(?:SSA)?\b", 1), (r"\bDR\.?\b", 0.7),
        (r"STUDIO\s+MEDICO", 1.5), (r"AMBULATORIO", 0.7), (r"POLIAMBULATORI", 1),
        (r"CARDIOLOG|DERMATOLOG|GINECOLOG|OCULIST|OTORINO|NEUROLOG|UROLOG|PEDIATR|ENDOCRINOLOG|"
         r"GASTROENTEROLOG|PNEUMOLOG|REUMATOLOG|ALLERGOLOG|ONCOLOG|PSICHIATR|ANGIOLOG|NEFROLOG", 2),
        (r"CONSULTO|CONSULENZA\s+MEDICA", 1.5), (r"PRESTAZIONE\s+MEDICA|PRESTAZIONI\s+MEDICHE", 1),
        (r"MEDICO\s+CHIRURGO", 1.5),
    ],
    "esami_analisi": [
        (r"ANALISI", 2.5), (r"LABORATORIO", 2), (r"\bESAM[EI]\b", 2), (r"PRELIEV", 2), (r"ECOGRAFI", 2.5),
        (r"RADIOGRAFI|\bRX\b|RADIOLOG", 2.5), (r"RISONANZA|\bRMN?\b|\bTAC\b", 2.5), (r"\bECG\b|ELETTROCARDIOGRAMM", 2),
        (r"MAMMOGRAFI|MOC\b|DENSITOMETR", 2.5), (r"DIAGNOSTIC", 1.5), (r"EMOCROMO|GLICEMIA|COLESTEROL", 1.5),
        (r"HOLTER|SPIROMETR|ECODOPPLER|DOPPLER|ENDOSCOPI|COLONSCOPI|GASTROSCOPI", 2.5), (r"TAMPONE", 1.5),
    ],
    "cure_dentistiche": [
        (r"DENTIST", 3), (r"ODONTOIATR", 3), (r"ODONTO", 2), (r"ORTODONZ", 3), (r"IGIENE\s+ORALE|DETARTRASI|ABLAZIONE", 3),
        (r"IMPLANT", 2), (r"OTTURAZION|DEVITALIZZ|CARIE|ESTRAZIONE", 2.5), (r"PROTESI\s+DENTAL|CORONA\b|BITE\b", 2),
        (r"PARODONT|ENDODONZ|SBIANCAMENT", 2),
    ],
    "prestazioni_sanitarie": [
        (r"FISIOTERAP|FISIOKINESI|KINESITERAP", 3), (r"PSICOLOG|PSICOTERAP", 3), (r"LOGOPED", 3), (r"OSTEOPAT", 3),
        (r"INFERMIER", 2.5), (r"RIABILITAZ", 2.5), (r"PODOLOG", 3), (r"NUTRIZIONIST|DIETIST|BIOLOGO\s+NUTRIZ", 3),
        (r"CHIROPRAT", 2.5), (r"TERAPIA\b|TERAPIE\b|TECAR|LASERTERAP|ONDE\s+D.?URTO|MAGNETOTERAP", 1.5),
        (r"OSTETRIC", 2), (r"AGOPUNTUR", 2), (r"MASSOFISIOTERAP", 2.5), (r"ORTOTTIST", 2.5),
    ],
    "ricoveri_interventi": [
        (r"RICOVER", 3), (r"INTERVENT[OI]\s+CHIRURG", 3), (r"CHIRURGI", 1.5), (r"DEGENZA", 3), (r"DAY\s+HOSPITAL|DAY\s+SURGERY", 3),
        (r"CASA\s+DI\s+CURA", 2), (r"\bCLINICA\b", 1), (r"SALA\s+OPERATORIA", 2.5),
    ],
    "veterinarie_farmaci": [(r"FARMAC\w*\s+(?:AD\s+)?USO\s+VETERINARIO|VETERINARI\w*.*FARMAC|FARMAC\w*.*VETERINAR", 4)],
    "veterinarie_prestazioni": [
        (r"VETERINAR", 3), (r"AMBULATORIO\s+VETERINARIO|CLINICA\s+VETERINARIA|MEDICO\s+VETERINARIO", 2),
    ],
    "non_detraibile": [
        (r"PARAFARMACIA", 1.5), (r"COSMETIC|DERMOCOSM", 1.5), (r"ERBORISTERIA", 2.5), (r"PROFUMERIA", 2.5),
        (r"INTEGRATOR", 1),
    ],
}  # fmt: skip

_SSN_PROVIDER = re.compile(
    r"\bA\.?S\.?L\.?\b|\bASST\b|\bAUSL\b|\bULSS\b|\bUSL\b|AZIENDA\s+(?:SANITARIA|OSPEDALIER|SOCIO)|"
    r"\bS\.?S\.?N\.?\b|SERVIZIO\s+SANITARIO|ACCREDITAT|CONVENZIONAT|\bTICKET\b|OSPEDALE|POLICLINICO|"
    r"\bI\.?R\.?C\.?C\.?S\.?\b|COMPARTECIPAZIONE"
)


def extract_category(text_kw: str) -> tuple[str | None, float]:
    scores: dict[str, float] = {}
    for cat, pats in CATEGORY_KEYWORDS.items():
        s = 0.0
        for pat, w in pats:
            if re.search(pat, text_kw):
                s += w
        if s:
            scores[cat] = s
    if not scores:
        return None, 0.0
    # Veterinary context wins over generic human-health keywords.
    if "veterinarie_farmaci" in scores:
        return "veterinarie_farmaci", 0.8
    if scores.get("veterinarie_prestazioni", 0) >= 3:
        return "veterinarie_prestazioni", 0.8
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_s = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    conf = 0.35 + min(0.35, top_s * 0.08) + min(0.25, (top_s - second) * 0.1)
    return top, round(min(conf, 0.95), 2)


# --------------------------------------------------------------------------- items

_ITEM_NON_DEDUCTIBLE = re.compile(
    r"PARAFARMAC|COSMETIC|DERMOCOSM|INTEGRATOR|ALIMENT|IGIENE\s+(?:PERSONALE|INTIMA)|SHAMPOO|BAGNOSCHIUMA|"
    r"DENTIFRICI|COLLUTORI|SPAZZOLIN|PANNOLIN|SHOPPER|SACCHETT|BORSA|ERBORIST|TISANA|CARAMELL|SOLARE|"
    r"PROFUM|MAKE\s*UP|DEODORANT|OMAGGIO|BUONO|GIFT"
)
_ITEM_DEDUCTIBLE = re.compile(
    r"FARMAC|MEDICINAL|\bSOP\b|\bOTC\b|OMEOPAT|TICKET|DISPOSITIV|DISP\.?\s*MED|\bD\.?M\.?\b|GALENIC|"
    r"PREPARAZ|VISITA|PRESTAZION|ESAM[EI]|ANALISI|LENTI|OCCHIAL|ONORARIO|COMPENSO|SEDUTA|TRATTAMENTO|"
    r"INTERVENTO|IGIENE\s+ORALE|DETARTRASI|ECOGRAFI|RADIOGRAF"
)
_ITEM_SKIP = re.compile(
    r"TOTALE|SUBTOT|\bIVA\b|IMPONIBILE|PAGAMENTO|PAGATO|RESTO|SCONTO|CONTANT|ELETTRONIC|DI\s+CUI|BANCOMAT|"
    r"CARTA|\bPOS\b|ARROTOND|DOCUMENTO|SCONTRINO|\bRT\b|MATRICOLA|P\.?\s*IVA|C\.?\s*F\.?|TEL|FAX|VIA\b|"
    r"PIAZZA|CORSO|VIALE|CAP\b|BOLLO|RITENUTA|NUMERO|\bN\.|EURO\s*$"
)


def extract_items(lines: list[str], total_idx: int | None) -> list[LineItem]:
    end = total_idx if total_idx is not None else len(lines)
    items: list[LineItem] = []
    for line in lines[:end]:
        kw = _kw(line)
        if _ITEM_SKIP.search(kw):
            continue
        vals = amounts_in(line)
        if not vals:
            continue
        desc = AMOUNT_RE.sub("", _strip_dates(line))
        desc = re.sub(r"\d+(?:[.,]\d+)?\s?%", "", desc)
        desc = re.sub(r"[^\w\s./'-]", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" .-")
        if sum(c.isalpha() for c in desc) < 3:
            continue
        ded: bool | None = None
        if _ITEM_NON_DEDUCTIBLE.search(kw):
            ded = False
        elif _ITEM_DEDUCTIBLE.search(kw):
            ded = True
        items.append(LineItem(description=desc[:80], amount_cents=vals[-1], deductible=ded))
    return items


# --------------------------------------------------------------------------- provider / ids

_PROVIDER_KW = re.compile(
    r"FARMACIA|PARAFARMACIA|STUDIO|\bDOTT\.?|\bDR\.?\b|CENTRO|OSPEDALE|\bA\.?S\.?L\b|\bASST\b|\bAUSL\b|\bULSS\b|"
    r"POLIAMBULATORI|LABORATORI|OTTICA|CLINICA|CASA\s+DI\s+CURA|AZIENDA|AMBULATORIO|ISTITUTO|POLICLINICO|"
    r"SANITARIA|ODONTO|DENTIST|FISIO|MEDIC|VETERINAR|S\.?R\.?L|S\.?P\.?A|S\.?N\.?C|S\.?A\.?S|COOP"
)
_NOT_PROVIDER = re.compile(
    r"DOCUMENTO|COMMERCIALE|SCONTRINO|FATTURA|RICEVUTA|^\s*VIA\b|\bVIA\s|PIAZZA|VIALE|CORSO|TEL|FAX|"
    r"P\.?\s*IVA|PARTITA|C\.?\s*F\.?\b|CODICE|WWW|HTTP|@|DESCRIZIONE|PREZZO|BENVENUT|GRAZIE|^\s*\d{5}\b|"
    r"SPETT|EGREGI|GENTILE|DESTINATARIO|CLIENTE|PAZIENTE|\bSIG\.?"
)


def _clean_name(line: str) -> str:
    s = re.sub(r"[^\w\s.&'’,-]", " ", line)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    return s[:80]


def extract_provider(lines: list[str]) -> tuple[str | None, float]:
    head = [ln for ln in lines[:10] if ln.strip()]
    for ln in head:
        kw = _kw(ln)
        if _PROVIDER_KW.search(kw) and not _NOT_PROVIDER.search(kw):
            name = _clean_name(ln)
            if sum(c.isalpha() for c in name) >= 4:
                return name, 0.8
    for ln in head[:4]:
        kw = _kw(ln)
        name = _clean_name(ln)
        letters = sum(c.isalpha() for c in name)
        digits = sum(c.isdigit() for c in name)
        if letters >= 4 and digits <= 2 and not _NOT_PROVIDER.search(kw):
            return name, 0.45
    return None, 0.0


_DOCNUM_RE = re.compile(
    r"(?:FATTURA|RICEVUTA|DOCUMENTO|DOC\.?|SCONTRINO|NOTA|PARCELLA)[^\n]{0,25}?"
    r"(?:\bN(?:UMERO|R|UM)?\b\.?|N°|Nº|NO\.|#)\s*[:.]?\s*([A-Z0-9][A-Z0-9/_.-]{0,24})"
)


def extract_document_number(lines: list[str]) -> tuple[str | None, float]:
    for ln in lines:
        m = _DOCNUM_RE.search(_kw(ln))
        if m:
            num = m.group(1).strip(".-/")
            if num and any(c.isdigit() for c in num) and not re.fullmatch(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", num):
                return num, 0.7
    return None, 0.0


_PATIENT_KW = re.compile(
    r"CLIENTE|PAZIENTE|ACQUIRENTE|INTESTAT|\bSIG\b|\bSIG\.|SIGNOR|DESTINATARIO|ASSISTIT|BENEFICIARI|"
    r"C\.?\s*F\.?\s*CLIENTE|SPETT|EGREGI|GENTILE|COD(?:ICE)?\.?\s+FISC(?:ALE)?\s+(?:DEL\s+)?(?:CLIENTE|PAZIENTE)"
)
_PROVIDER_ID_KW = re.compile(r"P\.?\s*IVA|PARTITA\s+IVA|\bDOTT|\bDR\b|STUDIO|MEDICO|C\.?F\.?\s*/\s*P")


def extract_tax_codes(
    lines: list[str], text: str, known: dict[str, str]
) -> tuple[str | None, float, str | None, str | None]:
    """Return (patient CF, confidence, beneficiary id, provider CF)."""
    cfs = validators.find_cfs(text)
    if not cfs:
        return None, 0.0, None, None
    # Map offsets to line indices.
    starts = []
    pos = 0
    for ln in text.splitlines(keepends=True):
        starts.append(pos)
        pos += len(ln)

    def line_of(off: int) -> int:
        idx = 0
        for i, s in enumerate(starts):
            if s <= off:
                idx = i
        return idx

    patient: tuple[float, str] | None = None
    provider_cf: str | None = None
    for cf, off in cfs:
        if cf in known:
            return cf, 0.95, known[cf], next((c for c, _ in cfs if c != cf and c not in known), None)
        li = line_of(off)
        ctx = _kw(" ".join(lines[max(0, li - 1) : li + 1])) if li < len(lines) else ""
        same = _kw(lines[li]) if li < len(lines) else ""
        score = 0.45
        if _PATIENT_KW.search(ctx):
            score += 0.35
        if _PROVIDER_ID_KW.search(same) or li < 4:
            score -= 0.3
        if score < 0.3:
            provider_cf = provider_cf or cf
            continue
        if patient is None or score > patient[0]:
            if patient is not None:
                provider_cf = provider_cf or patient[1]
            patient = (score, cf)
    if patient is None:
        return None, 0.0, None, provider_cf
    return patient[1], round(min(patient[0], 0.9), 2), None, provider_cf


def extract_vat(text: str, exclude: set[str]) -> tuple[str | None, float]:
    found = [p for p in validators.find_pivas(text) if p[0] not in exclude]
    if not found:
        return None, 0.0
    labelled = [p for p in found if p[2]]
    if labelled:
        return labelled[0][0], 0.9
    return found[0][0], 0.55


# --------------------------------------------------------------------------- main entry


EXEMPT_CF_WARNING_CATEGORIES = {"farmaci", "dispositivi_medici", "occhiali_lenti"}


def parse_receipt_text(text: str, known_tax_codes: dict[str, str] | None = None, today: date | None = None) -> ParsedReceipt:
    """Parse OCR text. ``known_tax_codes`` maps codice fiscale -> beneficiary id."""
    today = today or date.today()
    known = {k.upper(): v for k, v in (known_tax_codes or {}).items()}
    raw_lines = [ln.rstrip() for ln in (text or "").splitlines()]
    lines = [ln for ln in raw_lines if ln.strip()]
    clean_text = "\n".join(lines)
    text_kw = _kw(clean_text)

    r = ParsedReceipt()

    dt, c = extract_date(lines, today)
    if dt:
        r.date, r.confidence["date"] = dt.isoformat(), round(c, 2)

    total, c, total_idx = extract_total(lines)
    if total is not None:
        r.amount_cents, r.confidence["amount_cents"] = total, round(c, 2)

    r.provider_name, c = extract_provider(lines)
    if r.provider_name:
        r.confidence["provider_name"] = c

    cf, c, beneficiary, provider_cf = extract_tax_codes(lines, clean_text, known)
    if cf:
        r.patient_tax_code, r.confidence["patient_tax_code"] = cf, c
        r.beneficiary = beneficiary
    r.provider_tax_code = provider_cf

    exclude = {cf} if cf else set()
    r.provider_vat, c = extract_vat(clean_text, exclude)
    if r.provider_vat:
        r.confidence["provider_vat"] = c

    r.document_number, c = extract_document_number(lines)
    if r.document_number:
        r.confidence["document_number"] = c

    r.payment_method, c = extract_payment(lines)
    r.confidence["payment_method"] = c

    r.category, c = extract_category(text_kw)
    if r.category:
        r.confidence["category"] = c

    r.ssn_provider = bool(_SSN_PROVIDER.search(text_kw))
    if r.category == "ticket_ssn":
        r.ssn_provider = True

    r.items = extract_items(lines, total_idx)
    non_ded = sum(i.amount_cents for i in r.items if i.deductible is False)
    if r.amount_cents and non_ded and non_ded < r.amount_cents:
        r.deductible_cents = r.amount_cents - non_ded
        r.warnings.append(
            f"Lo scontrino contiene articoli probabilmente non detraibili per € {format_cents(non_ded)} "
            "(parafarmaci, cosmetici, integratori…): l'importo detraibile è stato ridotto."
        )
        if r.category in (None, "non_detraibile") and any(i.deductible for i in r.items):
            r.category = "farmaci"

    if r.date is None:
        r.warnings.append("Data non riconosciuta.")
    if r.amount_cents is None:
        r.warnings.append("Importo totale non riconosciuto.")
    elif r.confidence.get("amount_cents", 0) < 0.5:
        r.warnings.append("Importo totale incerto: verificalo sull'immagine.")
    if r.patient_tax_code is None and (r.category in EXEMPT_CF_WARNING_CATEGORIES or r.category is None):
        r.warnings.append(
            "Codice fiscale del destinatario non trovato: per la detrazione deve comparire sul documento "
            "(scontrino parlante o fattura intestata)."
        )
    return r
