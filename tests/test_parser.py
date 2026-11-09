# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date

import pytest

import receipt_samples as S
from app.ocr.parser import amounts_in, format_cents, parse_amount_input, parse_receipt_text

TODAY = date(2026, 1, 15)
KNOWN = {"RSSMRA80A01H501U": "self", "RSSLCU12T10H501I": "fam-luca"}


def parse(text):
    return parse_receipt_text(text, KNOWN, today=TODAY)


def test_pharmacy_electronic():
    r = parse(S.PHARMACY_ELECTRONIC)
    assert r.date == "2025-03-09"
    assert r.amount_cents == 2340
    assert r.provider_vat == "01234567897"
    assert r.patient_tax_code == "RSSMRA80A01H501U" and r.beneficiary == "self"
    assert r.payment_method == "tracciabile"
    assert r.category == "farmaci"
    assert r.document_number == "0123-0045"
    assert r.provider_name.startswith("FARMACIA SAN MARCO")
    assert r.deductible_cents is None
    assert not r.warnings


def test_pharmacy_mixed_cash_reduces_deductible_and_repairs_cf():
    r = parse(S.PHARMACY_MIXED_CASH)
    assert r.amount_cents == 3100
    assert r.deductible_cents == 1600  # parafarmaco excluded
    assert r.payment_method == "contanti"
    assert r.patient_tax_code == "RSSMRA80A01H501U"  # OCR'd as RSSMRA8OA0lH5O1U
    assert any("non detraibili" in w for w in r.warnings)


def test_doctor_invoice_separates_doctor_and_patient_cf():
    r = parse(S.DOCTOR_INVOICE)
    assert r.date == "2025-05-21"
    assert r.amount_cents == 15200
    assert r.provider_tax_code == "VRDGPP70C15L219C"
    assert r.patient_tax_code == "BNCLRA85M41F205C"
    assert r.provider_vat == "03456789019"
    assert r.document_number == "45/2025"
    assert r.payment_method == "tracciabile"
    assert r.category == "visite_specialistiche"
    assert r.provider_name == "Dott. Giuseppe Verdi"


def test_ticket_asl():
    r = parse(S.TICKET_ASL)
    assert r.category == "ticket_ssn"
    assert r.ssn_provider is True
    assert r.amount_cents == 3615
    assert r.date == "2025-02-03"
    assert r.payment_method == "contanti"


def test_dentist_cash_family_member():
    r = parse(S.DENTIST_CASH)
    assert r.category == "cure_dentistiche"
    assert r.payment_method == "contanti"
    assert r.amount_cents == 20000
    assert r.date == "2025-10-07"  # "7 ottobre 2025"
    assert r.beneficiary == "fam-luca"


def test_optician_cash_amount_aware():
    r = parse(S.OPTICIAN)
    assert r.category == "occhiali_lenti"
    assert r.payment_method == "contanti"  # contante 57,00 / elettronico 0,00
    assert r.date == "2025-08-22"


def test_lab_accredited():
    r = parse(S.LAB_ANALYSIS)
    assert r.category == "esami_analisi"
    assert r.ssn_provider is True
    assert r.amount_cents == 1800
    assert r.payment_method == "tracciabile"
    assert r.patient_tax_code == "FRRGNN60B12A944C"


def test_vet():
    r = parse(S.VET_CLINIC)
    assert r.category == "veterinarie_prestazioni"
    assert r.amount_cents == 9500


def test_noisy_ocr():
    r = parse(S.NOISY_OCR)
    assert r.amount_cents == 740
    assert r.date == "2025-12-10"
    assert r.provider_vat == "02345678904"
    assert r.payment_method == "tracciabile"
    assert r.category == "farmaci"


def test_future_and_birth_dates_ignored():
    text = "STUDIO MEDICO\nNato il 01/02/1980\nData 05/06/2025\nVisita 100,00\nTOTALE 100,00\nprossima visita 01/01/2027"
    assert parse(text).date == "2025-06-05"


def test_empty_text():
    r = parse("")
    assert r.amount_cents is None and r.date is None and r.warnings


def test_amounts():
    assert amounts_in("TOTALE 1.234,56") == [123456]
    assert amounts_in("IVA 10,00% 1,14") == [114]
    assert amounts_in("09-03-2025 10:22") == []
    assert amounts_in("TOT 12.50 EUR") == [1250]


@pytest.mark.parametrize(
    "raw,cents",
    [("12,50", 1250), ("1.234,56", 123456), ("12.5", 1250), ("€ 7", 700), ("1.234", 123400), ("0,99", 99), ("", None)],
)
def test_parse_amount_input(raw, cents):
    assert parse_amount_input(raw) == cents


def test_parse_amount_input_invalid():
    with pytest.raises(ValueError):
        parse_amount_input("abc")


def test_format_cents():
    assert format_cents(123456) == "1.234,56"
    assert format_cents(5) == "0,05"
