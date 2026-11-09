# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validators for Italian tax identifiers, tolerant to common OCR confusions."""

from __future__ import annotations

import itertools
import re

# --- codice fiscale -------------------------------------------------------

_CF_ODD = {
    **dict(zip("0123456789", [1, 0, 5, 7, 9, 13, 15, 17, 19, 21])),
    **dict(
        zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23],
        )
    ),
}
_CF_EVEN = {**{str(i): i for i in range(10)}, **{c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}}

# Positions (0-based) that hold digits in a regular CF; omocodia may replace
# them with one of these letters.
_CF_DIGIT_POS = (6, 7, 9, 10, 12, 13, 14)
_OMOCODIA = "LMNPQRSTUV"
_MONTHS = "ABCDEHLMPRST"

CF_PATTERN = re.compile(r"[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]")

# OCR look-alikes: what a letter slot may have been misread as, and vice versa.
_DIGIT_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
_LETTER_TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "A": "4", "S": "5", "G": "6", "B": "8"}


def cf_check_char(first15: str) -> str:
    total = 0
    for i, ch in enumerate(first15):
        total += _CF_ODD[ch] if i % 2 == 0 else _CF_EVEN[ch]
    return chr(ord("A") + total % 26)


def is_valid_cf(cf: str) -> bool:
    cf = (cf or "").strip().upper()
    if len(cf) != 16 or not CF_PATTERN.fullmatch(cf):
        return False
    return cf_check_char(cf[:15]) == cf[15]


def _cf_slot_options(i: int, ch: str) -> list[str]:
    """Plausible true characters for position ``i`` given the OCR'd character."""
    if i in _CF_DIGIT_POS:
        opts = [ch] if (ch.isdigit() or ch in _OMOCODIA) else []
        if ch in _LETTER_TO_DIGIT and _LETTER_TO_DIGIT[ch] not in opts:
            opts.append(_LETTER_TO_DIGIT[ch])
        return opts
    if i == 8:
        opts = [ch] if ch in _MONTHS else []
        alt = _DIGIT_TO_LETTER.get(ch)
        if alt and alt in _MONTHS:
            opts.append(alt)
        return opts
    opts = [ch] if ch.isalpha() else []
    if ch in _DIGIT_TO_LETTER:
        opts.append(_DIGIT_TO_LETTER[ch])
    return opts


def repair_cf(candidate: str, max_fixes: int = 3) -> str | None:
    """Try to turn a 16-char OCR string into a valid codice fiscale.

    Only substitutions between visually similar characters are attempted and
    the result must pass the check character, so false positives are rare.
    """
    c = re.sub(r"[^A-Z0-9]", "", (candidate or "").upper())
    if len(c) != 16:
        return None
    if is_valid_cf(c):
        return c
    options = [_cf_slot_options(i, ch) for i, ch in enumerate(c)]
    if any(not o for o in options):
        return None
    ambiguous = [i for i, o in enumerate(options) if len(o) > 1 or o[0] != c[i]]
    if len(ambiguous) > 8:
        return None
    for combo in itertools.product(*options):
        fixes = sum(1 for i, ch in enumerate(combo) if ch != c[i])
        if fixes > max_fixes:
            continue
        s = "".join(combo)
        if is_valid_cf(s):
            return s
    return None


def find_cfs(text: str) -> list[tuple[str, int]]:
    """Return (codice fiscale, offset) pairs found in ``text`` (validated, de-duplicated)."""
    found: dict[str, int] = {}
    up = text.upper()
    for m in CF_PATTERN.finditer(up):
        if is_valid_cf(m.group(0)):
            found.setdefault(m.group(0), m.start())
    # OCR often splits or mangles the code: scan 16-char alnum windows per line.
    offset = 0
    for line in up.splitlines(keepends=True):
        compact_chars = [(ch, offset + i) for i, ch in enumerate(line) if ch.isalnum()]
        compact = "".join(ch for ch, _ in compact_chars)
        for i in range(0, max(0, len(compact) - 15)):
            window = compact[i : i + 16]
            if sum(ch.isdigit() for ch in window) < 3 or sum(ch.isalpha() for ch in window) < 5:
                continue
            fixed = repair_cf(window, max_fixes=3)
            if fixed:
                found.setdefault(fixed, compact_chars[i][1])
        offset += len(line)
    return sorted(found.items(), key=lambda kv: kv[1])


# --- partita IVA ----------------------------------------------------------


def is_valid_piva(piva: str) -> bool:
    p = re.sub(r"\D", "", piva or "")
    if len(p) != 11 or p == "0" * 11:
        return False
    total = 0
    for i, ch in enumerate(p[:10]):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(p[10])


def find_pivas(text: str) -> list[tuple[str, int, bool]]:
    """Return (P.IVA, offset, labelled) for valid 11-digit numbers in ``text``."""
    out: dict[str, tuple[int, bool]] = {}
    norm = text.upper()
    for m in re.finditer(r"(?<![0-9])((?:IT)?\s*[0-9OIl ]{11,14})(?![0-9])", norm):
        raw = m.group(1)
        digits = raw.replace("IT", "").replace(" ", "").replace("O", "0").replace("I", "1").replace("L", "1")
        if len(digits) != 11 or not digits.isdigit() or not is_valid_piva(digits):
            continue
        start = m.start(1)
        before = norm[max(0, start - 25) : start]
        labelled = bool(re.search(r"(P\s*[.,]?\s*I\s*V\s*A|PARTITA|P\.\s*I\.|VAT|\bIT\b)", before + raw[:2]))
        if digits not in out or (labelled and not out[digits][1]):
            out[digits] = (start, labelled)
    return sorted(((k, v[0], v[1]) for k, v in out.items()), key=lambda t: t[1])
