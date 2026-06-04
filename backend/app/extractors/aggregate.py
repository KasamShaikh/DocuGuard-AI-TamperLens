from ..config import get_settings

settings = get_settings()

# Weighted contribution of each extractor to the combined tamper score.
# Favours the reliable document-native, vision and structured (checksum) signals
# over classical pixel heuristics, which are weak on digital documents.
WEIGHTS = {
    "pdf_forensics": 0.22,
    "vision_judge": 0.22,
    "id_checksums": 0.20,
    "content_consistency": 0.12,
    "compression_ela": 0.12,
    "copy_move": 0.06,
    "metadata": 0.04,
    "ai_generation": 0.02,
}

# Soft heuristics that may corroborate but must NOT single-handedly drive the
# verdict. Pixel "AI-generation" noise cues fire on clean PNGs/scans too, so we
# exclude them from the don't-miss-it max floor (they still count in the average).
SOFT_SIGNALS = {"ai_generation"}


def aggregate(extractor_results: list[dict]) -> dict:
    """Combine per-extractor scores into a single tamper score and decision.

    Fraud screening is a "noisy-or" problem: any one credible forensic signal is
    meaningful and must NOT be diluted to zero by calm detectors. We therefore
    combine a weighted average (overall picture) with the strongest single
    detector (don't-miss-it floor), and apply hard-trigger overrides.
    """
    by_name = {r["name"]: r for r in extractor_results}

    weighted = 0.0
    weight_total = 0.0
    for name, weight in WEIGHTS.items():
        if name in by_name:
            weighted += by_name[name]["score"] * weight
            weight_total += weight

    weighted_avg = weighted / weight_total if weight_total else 0.0

    # Strongest individual *reliable* detector — the floor that prevents
    # dilution. Soft heuristics are excluded so they corroborate but never force
    # a verdict on their own (this is what kept clean docs pinned near 0.51).
    max_score = max(
        (r["score"] for n, r in by_name.items() if n not in SOFT_SIGNALS),
        default=0.0,
    )

    # Blend: keep most of the strongest signal, plus the corroborating average.
    # A single 0.6 detector alone -> ~0.51 (review); multiple signals push higher.
    tamper_score = max(weighted_avg, 0.85 * max_score)

    # Hard triggers: any extractor that is highly confident forces a high floor.
    hard_triggers: list[str] = []
    for name, r in by_name.items():
        if r["score"] >= 0.7:
            hard_triggers.append(name)
            tamper_score = max(tamper_score, 0.75)

    tamper_score = round(min(tamper_score, 1.0), 3)

    if tamper_score >= settings.tamper_threshold_reject:
        decision = "reject"
    elif tamper_score >= settings.tamper_threshold_review:
        decision = "review"
    else:
        decision = "accept"

    return {
        "tamper_score": tamper_score,
        "decision": decision,
        "hard_triggers": hard_triggers,
        "weighted_avg": round(weighted_avg, 3),
        "max_detector": round(max_score, 3),
        "weights": WEIGHTS,
    }
