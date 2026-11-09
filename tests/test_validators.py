# SPDX-License-Identifier: AGPL-3.0-or-later
from app.ocr import validators as v


def test_valid_cf():
    assert v.is_valid_cf("RSSMRA80A01H501U")
    assert not v.is_valid_cf("RSSMRA80A01H501X")
    assert not v.is_valid_cf("RSSMRA80A01H501")


def test_omocodia_cf_is_valid():
    # Omocodia replaces digits with letters (0->L, 1->M...). Recompute the check char.
    base = "RSSMRA80A01H50M"
    assert v.is_valid_cf(base + v.cf_check_char(base))


def test_repair_cf_ocr_confusions():
    assert v.repair_cf("RSSMRA8OA0lH5O1U") == "RSSMRA80A01H501U"
    assert v.repair_cf("R5SMRA80A01H501U") == "RSSMRA80A01H501U"
    assert v.repair_cf("XXXXXXXXXXXXXXXX") is None


def test_find_cfs_with_spaces():
    found = v.find_cfs("C.F. CLIENTE: RSSMRA 80A01 H501U\naltro")
    assert [cf for cf, _ in found] == ["RSSMRA80A01H501U"]


def test_piva():
    assert v.is_valid_piva("01234567897")
    assert not v.is_valid_piva("01234567890")
    assert not v.is_valid_piva("00000000000")
    found = v.find_pivas("FARMACIA\nP.IVA IT 01234567897\nTEL 0212345678")
    assert found[0][0] == "01234567897" and found[0][2] is True
