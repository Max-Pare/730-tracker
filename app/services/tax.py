# SPDX-License-Identifier: AGPL-3.0-or-later
"""730 rules for medical (and veterinary) expenses, and yearly summaries.

References (Agenzia delle Entrate, 730 instructions, quadro E, rigo E1/E8-E10):
* spese sanitarie: detrazione IRPEF 19% della parte eccedente la franchigia di € 129,11;
* spese veterinarie (codice 29): 19% su un massimo di € 550, franchigia € 129,11;
* dal 2020 la detrazione spetta solo con pagamento tracciabile, tranne per
  medicinali, dispositivi medici e prestazioni di strutture pubbliche o
  private accreditate al SSN (L. 160/2019, art. 1 c. 679-680);
* spese sanitarie oltre € 15.493,71: possibile rateizzazione in 4 anni.

The figures produced here are **estimates** to help prepare the return; they
do not replace the official 730 or professional advice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .domain import CATEGORIES, ReceiptData
from .profile import Profile

DETRACTION_RATE_PERCENT = 19
FRANCHISE_CENTS = 12_911
VET_CAP_CENTS = 55_000
INSTALMENT_THRESHOLD_CENTS = 1_549_371

MONTHS_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def percent(cents: int, pct: int = DETRACTION_RATE_PERCENT) -> int:
    """Round-half-up percentage of an amount in cents."""
    return (cents * pct + 50) // 100


@dataclass
class Evaluation:
    status: str  # "detraibile" | "non_detraibile" | "da_verificare"
    group: str | None
    eligible_cents: int
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return {"detraibile": "Detraibile", "non_detraibile": "Non detraibile", "da_verificare": "Da verificare"}[self.status]


def evaluate(d: ReceiptData, profile: Profile) -> Evaluation:
    warnings = d.field_warnings()
    if d.amount_cents is None:
        return Evaluation("da_verificare", None, 0, ["Importo mancante."], warnings)
    if not d.category:
        return Evaluation("da_verificare", None, 0, ["Categoria di spesa non indicata."], warnings)
    cat = CATEGORIES[d.category]
    if cat.group is None:
        return Evaluation("non_detraibile", None, 0, ["Spesa non detraibile."], warnings)
    if d.date is None:
        return Evaluation("da_verificare", cat.group, 0, ["Data di pagamento mancante: serve a stabilire l'anno."], warnings)

    if cat.group == "sanitarie" and d.beneficiary != "self":
        member = profile.member(d.beneficiary)
        if member is not None and not member.dependent:
            return Evaluation(
                "non_detraibile",
                cat.group,
                0,
                [f"{member.name} non è a carico: le sue spese sanitarie non sono detraibili da te (salvo patologie esenti)."],
                warnings,
            )

    eligible = d.effective_deductible_cents or 0
    if not cat.trace_exempt and not d.ssn_provider:
        if d.payment_method == "contanti":
            return Evaluation(
                "non_detraibile",
                cat.group,
                0,
                [
                    "Pagata in contanti: per questa spesa la detrazione richiede un pagamento tracciabile "
                    "(carta, bancomat, bonifico), salvo strutture pubbliche o accreditate SSN."
                ],
                warnings,
            )
        if d.payment_method == "sconosciuto":
            return Evaluation(
                "da_verificare",
                cat.group,
                eligible,
                ["Metodo di pagamento non indicato: è detraibile solo se tracciabile."],
                warnings,
            )

    if not d.patient_tax_code and cat.group == "sanitarie":
        warnings.append("Sul documento dovrebbe comparire il codice fiscale di chi ha sostenuto la spesa.")
    if d.deductible_cents is not None and d.amount_cents and d.deductible_cents < d.amount_cents:
        warnings.append("Solo una parte dell'importo è detraibile.")
    return Evaluation("detraibile", cat.group, eligible, [], warnings)


# --------------------------------------------------------------------------- yearly summary


@dataclass
class Bucket:
    key: str
    label: str
    count: int = 0
    total_cents: int = 0
    eligible_cents: int = 0


@dataclass
class Issue:
    receipt_id: str
    title: str
    message: str
    severity: str  # "warning" | "info"


@dataclass
class YearSummary:
    year: int
    return_label: str
    receipts_count: int = 0
    drafts_count: int = 0
    to_verify_count: int = 0
    non_deductible_count: int = 0
    total_spent_cents: int = 0
    sanitarie_eligible_cents: int = 0
    sanitarie_base_cents: int = 0
    sanitarie_detraction_cents: int = 0
    vet_eligible_cents: int = 0
    vet_base_cents: int = 0
    vet_detraction_cents: int = 0
    detraction_total_cents: int = 0
    uncertain_cents: int = 0
    non_deductible_cents: int = 0
    franchise_cents: int = FRANCHISE_CENTS
    franchise_remaining_cents: int = 0
    instalments_possible: bool = False
    by_month: list[Bucket] = field(default_factory=list)
    by_category: list[Bucket] = field(default_factory=list)
    by_beneficiary: list[Bucket] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(records, profile: Profile, year: int) -> YearSummary:
    """``records``: iterable of ReceiptRecord for the user (any year)."""
    s = YearSummary(year=year, return_label=f"730/{year + 1} (redditi {year})")
    months = [Bucket(str(i + 1), MONTHS_IT[i]) for i in range(12)]
    cats: dict[str, Bucket] = {}
    bens: dict[str, Bucket] = {}

    for r in records:
        d: ReceiptData = r.data
        if d.tax_year != year:
            continue
        if d.status == "bozza":
            s.drafts_count += 1
            s.issues.append(Issue(r.id, d.provider_name or "Scontrino", "Bozza da rivedere e confermare.", "info"))
            continue
        ev = evaluate(d, profile)
        amount = d.amount_cents or 0
        s.receipts_count += 1
        s.total_spent_cents += amount
        if d.status == "da_verificare":
            s.to_verify_count += 1

        if ev.status == "detraibile":
            if ev.group == "sanitarie":
                s.sanitarie_eligible_cents += ev.eligible_cents
            elif ev.group == "veterinarie":
                s.vet_eligible_cents += ev.eligible_cents
        elif ev.status == "da_verificare":
            s.uncertain_cents += ev.eligible_cents or amount
            s.issues.append(Issue(r.id, d.provider_name or "Scontrino", " ".join(ev.reasons), "warning"))
        else:
            s.non_deductible_count += 1
            s.non_deductible_cents += amount
            if d.category != "non_detraibile":
                s.issues.append(Issue(r.id, d.provider_name or "Scontrino", " ".join(ev.reasons), "warning"))
        for w in ev.warnings:
            s.issues.append(Issue(r.id, d.provider_name or "Scontrino", w, "info"))

        eligible = ev.eligible_cents if ev.status == "detraibile" else 0
        m = months[d.date.month - 1]
        m.count += 1
        m.total_cents += amount
        m.eligible_cents += eligible

        ck = d.category or "_none"
        cb = cats.setdefault(ck, Bucket(ck, CATEGORIES[ck].label if ck in CATEGORIES else "Senza categoria"))
        cb.count += 1
        cb.total_cents += amount
        cb.eligible_cents += eligible

        bk = d.beneficiary or "self"
        bb = bens.setdefault(bk, Bucket(bk, profile.beneficiary_label(bk)))
        bb.count += 1
        bb.total_cents += amount
        bb.eligible_cents += eligible

    s.sanitarie_base_cents = max(0, s.sanitarie_eligible_cents - FRANCHISE_CENTS)
    s.sanitarie_detraction_cents = percent(s.sanitarie_base_cents)
    s.franchise_remaining_cents = max(0, FRANCHISE_CENTS - s.sanitarie_eligible_cents)
    s.vet_base_cents = max(0, min(s.vet_eligible_cents, VET_CAP_CENTS) - FRANCHISE_CENTS)
    s.vet_detraction_cents = percent(s.vet_base_cents)
    s.detraction_total_cents = s.sanitarie_detraction_cents + s.vet_detraction_cents
    s.instalments_possible = s.sanitarie_eligible_cents > INSTALMENT_THRESHOLD_CENTS
    s.by_month = months
    s.by_category = sorted(cats.values(), key=lambda b: b.total_cents, reverse=True)
    s.by_beneficiary = sorted(bens.values(), key=lambda b: b.total_cents, reverse=True)
    return s
