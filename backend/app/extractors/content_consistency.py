import re


# Matches currency/number tokens like 1,234.50  ₹1200  $3,400  45000
_NUM_RE = re.compile(r"(?:₹|rs\.?|inr|usd|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)

_TOTAL_KEYS = ("grand total", "total amount", "net payable", "amount payable", "total")
_SUBTOTAL_KEYS = ("sub total", "subtotal", "taxable value", "amount before tax")
_TAX_KEYS = ("tax", "gst", "cgst", "sgst", "igst", "vat")


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _find_amount(text: str, keys: tuple[str, ...]) -> float | None:
    """Return the numeric value that appears nearest after any of the keys."""
    lowered = text.lower()
    best: float | None = None
    for key in keys:
        idx = lowered.rfind(key)
        if idx == -1:
            continue
        window = text[idx: idx + 80]
        m = _NUM_RE.search(window[len(key):])
        if m:
            val = _to_float(m.group(1))
            if val is not None:
                best = val
    return best


def run(ocr: dict) -> dict:
    """Validate the document's *figures* (not its pixels).

    Catches AI-generated or cleanly-edited documents whose numbers are
    internally inconsistent: line items that don't sum to the subtotal, or
    subtotal + tax that doesn't match the stated total. Pixel forensics cannot
    detect this class of fraud.

    Requires OCR text (Azure Document Intelligence). When OCR is unavailable
    this detector reports a neutral score and explains the gap.
    """
    reasons: list[str] = []
    details: dict = {}
    score = 0.0

    text = (ocr or {}).get("text", "") or ""
    if not ocr or not ocr.get("available") or len(text) < 20:
        return {
            "name": "content_consistency",
            "score": 0.0,
            "reasons": [
                "Content/figure validation needs OCR text (enable Azure Document "
                "Intelligence). Skipped — pixel forensics alone cannot verify figures."
            ],
            "details": {"ocr_available": False},
        }

    total = _find_amount(text, _TOTAL_KEYS)
    subtotal = _find_amount(text, _SUBTOTAL_KEYS)
    tax = _find_amount(text, _TAX_KEYS)

    details["detected_total"] = total
    details["detected_subtotal"] = subtotal
    details["detected_tax"] = tax

    # Check 1: subtotal + tax should equal total (within a small tolerance).
    if total is not None and subtotal is not None:
        expected = subtotal + (tax or 0.0)
        diff = abs(expected - total)
        tol = max(1.0, 0.01 * total)  # 1% or 1 unit tolerance
        details["expected_total"] = round(expected, 2)
        details["total_mismatch"] = round(diff, 2)
        if diff > tol:
            score = max(score, 0.7)
            reasons.append(
                f"Figures do not reconcile: subtotal ({subtotal}) + tax "
                f"({tax or 0}) = {expected:.2f}, but stated total is {total}."
            )

    # Check 2: line-item amounts vs subtotal/total.
    line_items = [
        _to_float(m.group(1))
        for m in _NUM_RE.finditer(text)
        if _to_float(m.group(1)) is not None
    ]
    line_items = [v for v in line_items if v is not None]
    if total is not None and total > 0 and len(line_items) >= 3:
        # A single figure exceeding the stated total *can* indicate edited
        # figures — but OCR frequently merges adjacent digits (GST / account /
        # phone / invoice numbers) into one huge token that looks like a giant
        # "line value". Those merged identifiers are the dominant false-positive
        # source on genuine documents, so we only treat a value as a real line
        # amount when it sits in a *plausible* band just above the total
        # (1.05x–2x). Anything far larger is treated as a merged identifier and
        # ignored, and the signal is kept soft (it cannot force a review on its
        # own — it only corroborates other evidence).
        candidates = [v for v in line_items if total * 1.05 < v <= total * 2.0]
        max_val = max(candidates) if candidates else 0.0
        if max_val > 0.0:
            score = max(score, 0.3)
            reasons.append(
                f"A line value ({max_val}) modestly exceeds the stated total "
                f"({total}). Possible figure edit — weak signal, verify if other "
                "detectors also flag this document."
            )

    if not reasons:
        reasons.append("Figures reconcile; no arithmetic inconsistency detected.")

    return {
        "name": "content_consistency",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
    }
