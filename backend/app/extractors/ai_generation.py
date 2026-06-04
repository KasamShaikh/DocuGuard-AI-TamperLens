import io

import cv2
import numpy as np
from PIL import Image


def _load_gray(image_bytes: bytes, max_dim: int = 1200) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    return np.asarray(img, dtype=np.float32)


def run(image_bytes: bytes) -> dict:
    """Heuristic detection of AI-generated / synthetic document images.

    Genuine scans and photos carry sensor/scan noise and a JPEG block grid.
    Diffusion/GAN-generated images tend to have (a) an unnaturally low and
    spatially-uniform high-frequency noise residual in flat regions, and
    (b) weak or missing 8x8 JPEG periodicity. This extractor measures both and
    flags images that look too "clean" to be a real capture.

    Pure NumPy/OpenCV; no external service required.
    """
    reasons: list[str] = []
    details: dict = {}
    score = 0.0

    try:
        gray = _load_gray(image_bytes)

        # --- Noise residual (high-pass) ---
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        residual = gray - blur

        # Focus on flat/background regions (where real noise is visible but
        # text edges are not). Use local-variance masking.
        local_mean = cv2.blur(gray, (9, 9))
        local_sq = cv2.blur(gray * gray, (9, 9))
        local_var = np.clip(local_sq - local_mean * local_mean, 0, None)
        flat_mask = local_var < 25.0  # smooth areas only

        if flat_mask.sum() > 500:
            flat_residual = residual[flat_mask]
            noise_std = float(np.std(flat_residual))
        else:
            noise_std = float(np.std(residual))
        details["flat_noise_std"] = round(noise_std, 4)

        # --- JPEG 8x8 periodicity via FFT of the residual ---
        h, w = residual.shape
        crop = residual[: (h // 8) * 8, : (w // 8) * 8]
        spectrum = np.abs(np.fft.fft2(crop))
        spectrum[0, 0] = 0  # drop DC
        # Energy at the 1/8 frequency bins (JPEG block periodicity).
        fy, fx = crop.shape
        peak = 0.0
        for ky in (fy // 8, fy - fy // 8):
            for kx in (fx // 8, fx - fx // 8):
                peak = max(peak, float(spectrum[ky % fy, kx % fx]))
        mean_energy = float(spectrum.mean()) + 1e-6
        jpeg_periodicity = peak / mean_energy
        details["jpeg_periodicity"] = round(jpeg_periodicity, 3)

        # --- Scoring (strict / corroboration-required) ---
        # A single "too clean" cue is NOT proof of AI generation: clean PNGs,
        # screenshots and digitally-rendered documents also have near-zero
        # background noise and no JPEG grid. We therefore treat this as a SOFT,
        # corroborating signal and only raise it when multiple cues agree. The
        # aggregator excludes this detector from the don't-miss-it floor, so it
        # can corroborate real tamper evidence but never force a verdict alone.
        very_low_noise = noise_std < 0.6
        low_noise = noise_std < 1.2
        weak_jpeg = jpeg_periodicity < 3.0

        if very_low_noise and weak_jpeg:
            score = 0.25
            reasons.append(
                "Background is very clean with no JPEG block structure. This is "
                "typical of a digitally-generated PDF/PNG export (most invoices "
                "and statements), and only weakly suggestive of an AI-generated "
                "image. Soft signal — not conclusive on its own."
            )
        elif low_noise and weak_jpeg:
            score = 0.15
            reasons.append(
                "Low background noise with weak JPEG block structure "
                "(common for digital exports / re-renders). Weak signal."
            )
        elif very_low_noise:
            score = 0.1
            reasons.append(
                "Very clean background (low noise). Common for digital/PNG "
                "documents; not conclusive of AI generation by itself."
            )
        else:
            reasons.append(
                "Noise and frequency characteristics are consistent with a real capture."
            )

    except Exception as exc:  # noqa: BLE001
        score = 0.0
        reasons = [f"Synthetic-image analysis skipped: {exc}"]

    return {
        "name": "ai_generation",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
    }
