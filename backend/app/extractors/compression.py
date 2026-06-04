import io

import numpy as np
from PIL import Image, ImageChops


def _to_rgb(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def run(image_bytes: bytes) -> dict:
    """Error Level Analysis (ELA).

    Re-saves the image at a known JPEG quality and measures per-region
    differences. Spliced/edited regions often compress differently from the
    untouched background, producing localized high-error areas.

    Returns a score plus an ELA heatmap (PNG bytes) for the overlay artifact.
    """
    reasons: list[str] = []
    details: dict = {}
    heatmap_png: bytes | None = None

    try:
        original = _to_rgb(image_bytes)

        buf = io.BytesIO()
        original.save(buf, "JPEG", quality=90)
        buf.seek(0)
        resaved = Image.open(buf).convert("RGB")

        ela = ImageChops.difference(original, resaved)
        ela_arr = np.asarray(ela, dtype=np.float32)

        # Per-pixel error magnitude.
        err = ela_arr.mean(axis=2)
        max_err = float(err.max()) if err.size else 0.0
        mean_err = float(err.mean()) if err.size else 0.0

        # Normalize error for heatmap rendering.
        if max_err > 0:
            norm = (err / max_err * 255.0).astype(np.uint8)
        else:
            norm = err.astype(np.uint8)

        # Suspicious = fraction of pixels whose error is far above the mean.
        if max_err > 0:
            high_thresh = mean_err + 0.35 * (max_err - mean_err)
            high_ratio = float((err > high_thresh).mean())
        else:
            high_ratio = 0.0

        details["mean_error"] = round(mean_err, 3)
        details["max_error"] = round(max_err, 3)
        details["high_error_ratio"] = round(high_ratio, 4)

        # Map the localized-error ratio into a suspicion score. A small,
        # concentrated high-error area is the strongest splice signal.
        score = min(high_ratio * 6.0, 1.0)

        if high_ratio > 0.04:
            score = max(score, 0.5)
            reasons.append("Localized high compression-error regions detected (possible splice/edit).")
        if mean_err > 12:
            score = max(score, 0.45)
            reasons.append("Globally elevated compression error (possible heavy re-encoding).")
        if not reasons:
            reasons.append("Compression error levels are uniform; no splicing signature found.")

        # Build heatmap PNG.
        heat = Image.fromarray(norm, mode="L").convert("RGB")
        out = io.BytesIO()
        heat.save(out, "PNG")
        heatmap_png = out.getvalue()

    except Exception as exc:  # noqa: BLE001 - extractor must not crash pipeline
        score = 0.0
        reasons = [f"Compression analysis skipped: {exc}"]

    return {
        "name": "compression_ela",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
        "heatmap_png": heatmap_png,
    }
