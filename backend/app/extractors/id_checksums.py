"""Tier 3 — identifier checksum & format validation.

A competent forger can make a document *look* perfect and make the arithmetic
reconcile, but structured identifiers carry built-in check digits that are hard
to fake by hand. Invalid IBAN / GSTIN / PAN / card checksums are strong evidence
that a field was edited or fabricated.

This detector is CPU-only and runs on OCR text (Azure Document Intelligence or
local Tesseract). It is conservative: it only scores when it both *finds* an
identifier and that identifier *fails* its checksum, so genuine documents are
not penalised for simply not containing a given ID type.
"""
from __future__ import annotations

import re

# India GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char
_GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z][0-9A-Z])\b")
# India PAN: 5 letters, 4 digits, 1 letter
_PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")
# IBAN: 2 letters, 2 digits, up to 30 alphanumerics
_IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b")
# Payment card: 13-19 digits (allowing spaces/dashes)
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _iban_ok(iban: str) -> bool:
    iban = iban.upper().replace(" ", "")
    if len(iban) < 15:
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


def _gstin_ok(gstin: str) -> bool:
    gstin = gstin.upper()
    if len(gstin) != 15:
        return False
    factor = 1
    total = 0
    mod = len(_GSTIN_CHARS)
    for ch in gstin[:14]:
        code = _GSTIN_CHARS.find(ch)
        if code < 0:
            return False
        addend = code * factor
        addend = (addend // mod) + (addend % mod)
        total += addend
        factor = 2 if factor == 1 else 1
    check = (mod - (total % mod)) % mod
    return _GSTIN_CHARS[check] == gstin[14]


def run(ocr: dict) -> dict:
    reasons: list[str] = []
    details: dict = {}
    score = 0.0

    text = (ocr or {}).get("text", "") or ""
    if not ocr or not ocr.get("available") or len(text) < 20:
        return {
            "name": "id_checksums",
            "score": 0.0,
            "reasons": [
                "Identifier validation needs OCR text (enable Azure Document "
                "Intelligence). Skipped."
            ],
            "details": {"ocr_available": False},
        }

    up = text.upper()
    checked: dict = {"gstin": [], "pan": [], "iban": [], "card": []}
    invalid: list[str] = []

    for m in _GSTIN_RE.finditer(up):
        val = m.group(1)
        ok = _gstin_ok(val)
        checked["gstin"].append({"value": val, "valid": ok})
        if not ok:
            invalid.append(f"GSTIN {val}")

    for m in _PAN_RE.finditer(up):
        # PAN has no public check digit; only a format/structure sanity flag.
        checked["pan"].append({"value": m.group(1), "valid": True})

    for m in _IBAN_RE.finditer(up):
        val = m.group(1)
        ok = _iban_ok(val)
        checked["iban"].append({"value": val, "valid": ok})
        if not ok:
            invalid.append(f"IBAN {val}")

    for m in _CARD_RE.finditer(text):
        raw = m.group(0)
        ok = _luhn_ok(raw)
        checked["card"].append({"value": raw.strip(), "valid": ok})
        if not ok:
            invalid.append(f"card number {raw.strip()}")

    details["checked"] = checked
    details["invalid"] = invalid

    if invalid:
        # An invalid check digit is strong, hard-to-fake evidence of editing.
        score = 0.75 if len(invalid) >= 2 else 0.6
        reasons.append(
            "Identifier checksum failed for: " + "; ".join(invalid) + ". "
            "Valid IBAN/GSTIN/card numbers must satisfy a check digit; failure "
            "indicates a fabricated or edited field (or a severe OCR error)."
        )
    else:
        any_found = any(checked[k] for k in checked)
        reasons.append(
            "All detected identifiers pass their checksums."
            if any_found
            else "No structured identifiers (IBAN/GSTIN/card) detected to validate."
        )

    return {
        "name": "id_checksums",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
    }
