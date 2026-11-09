# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date, datetime, timezone

from app.services.domain import ReceiptData
from app.services.profile import FamilyMember, Profile
from app.services.receipts import ReceiptRecord
from app.services.tax import evaluate, percent, summarize

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def rec(i, **kw):
    base = dict(status="verificato", date=date(2025, 3, 1), category="farmaci", payment_method="tracciabile")
    base.update(kw)
    return ReceiptRecord(str(i), NOW, NOW, ReceiptData(**base))


def test_percent_rounding():
    assert percent(10000) == 1900
    assert percent(1) == 0
    assert percent(3) == 1  # 0.57 -> 1


def test_franchise_applied_once():
    recs = [rec(1, amount_cents=10000), rec(2, amount_cents=20000)]
    s = summarize(recs, Profile(), 2025)
    assert s.sanitarie_eligible_cents == 30000
    assert s.sanitarie_base_cents == 30000 - 12911
    assert s.sanitarie_detraction_cents == percent(30000 - 12911)
    assert s.franchise_remaining_cents == 0


def test_below_franchise():
    s = summarize([rec(1, amount_cents=5000)], Profile(), 2025)
    assert s.detraction_total_cents == 0
    assert s.franchise_remaining_cents == 12911 - 5000


def test_cash_requires_traceability_except_exempt():
    p = Profile()
    assert evaluate(rec(1, amount_cents=100, category="visite_specialistiche", payment_method="contanti").data, p).status == "non_detraibile"
    assert evaluate(rec(1, amount_cents=100, category="visite_specialistiche", payment_method="contanti", ssn_provider=True).data, p).status == "detraibile"
    assert evaluate(rec(1, amount_cents=100, category="farmaci", payment_method="contanti").data, p).status == "detraibile"
    assert evaluate(rec(1, amount_cents=100, category="occhiali_lenti", payment_method="contanti").data, p).status == "detraibile"
    assert evaluate(rec(1, amount_cents=100, category="cure_dentistiche", payment_method="sconosciuto").data, p).status == "da_verificare"


def test_family_not_dependent_excluded():
    p = Profile(family=[FamilyMember(id="m1", name="Nonna", dependent=False), FamilyMember(id="m2", name="Luca")])
    assert evaluate(rec(1, amount_cents=100, beneficiary="m1").data, p).status == "non_detraibile"
    assert evaluate(rec(1, amount_cents=100, beneficiary="m2").data, p).status == "detraibile"


def test_vet_cap_and_separate_franchise():
    recs = [rec(1, amount_cents=80000, category="veterinarie_prestazioni"), rec(2, amount_cents=20000)]
    s = summarize(recs, Profile(), 2025)
    assert s.vet_eligible_cents == 80000
    assert s.vet_base_cents == 55000 - 12911
    assert s.vet_detraction_cents == percent(55000 - 12911)
    assert s.sanitarie_detraction_cents == percent(20000 - 12911)
    assert s.detraction_total_cents == s.vet_detraction_cents + s.sanitarie_detraction_cents


def test_partial_deductible_and_drafts_and_other_years():
    recs = [
        rec(1, amount_cents=30000, deductible_cents=20000),
        rec(2, amount_cents=99999, status="bozza"),
        rec(3, amount_cents=50000, date=date(2024, 5, 1)),
        rec(4, amount_cents=1000, category="non_detraibile"),
    ]
    s = summarize(recs, Profile(), 2025)
    assert s.sanitarie_eligible_cents == 20000
    assert s.drafts_count == 1
    assert s.receipts_count == 2
    assert s.total_spent_cents == 31000
    assert s.non_deductible_cents == 1000
    assert s.by_month[2].total_cents == 31000


def test_instalments_threshold():
    s = summarize([rec(1, amount_cents=1_600_000, category="ricoveri_interventi")], Profile(), 2025)
    assert s.instalments_possible
