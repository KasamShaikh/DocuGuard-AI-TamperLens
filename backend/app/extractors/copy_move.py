import io

import cv2
import numpy as np
from PIL import Image


def _to_gray(image_bytes: bytes, max_dim: int = 1000) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    # Downscale large images to keep feature matching fast.
    w, h = img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    return np.asarray(img, dtype=np.uint8)


def run(image_bytes: bytes) -> dict:
    """Copy-move detection via ORB keypoint self-matching.

    Detects regions duplicated within the same image (a classic tamper used to
    clone stamps, signatures, or hide content). Matches between spatially
    distant keypoints with near-identical descriptors indicate cloning.
    """
    reasons: list[str] = []
    details: dict = {}
    score = 0.0

    try:
        gray = _to_gray(image_bytes)
        h, w = gray.shape
        min_dist = 0.05 * float(np.hypot(w, h))  # ignore trivially-close matches

        orb = cv2.ORB_create(nfeatures=2000)
        keypoints, descriptors = orb.detectAndCompute(gray, None)

        cloned_pairs = 0
        if descriptors is not None and len(keypoints) > 10:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            # k=3 so we can skip the trivial self-match (a descriptor matches itself).
            knn = bf.knnMatch(descriptors, descriptors, k=3)

            # Group distant near-identical matches by their translation offset.
            # A real copy-move forgery is a *cluster* of matches sharing the SAME
            # offset vector. Repeated text/logos in a clean document instead
            # produce matches scattered across many different offsets, so we only
            # flag when one offset accumulates many supporting pairs.
            offset_bin = 12  # px quantization of the translation vector
            offset_votes: dict[tuple[int, int], int] = {}

            for matches in knn:
                for m in matches:
                    if m.queryIdx == m.trainIdx:
                        continue  # self match
                    if m.distance > 20:  # require near-identical descriptors
                        continue
                    p1 = np.array(keypoints[m.queryIdx].pt)
                    p2 = np.array(keypoints[m.trainIdx].pt)
                    dvec = p2 - p1
                    if np.linalg.norm(dvec) < min_dist:
                        continue  # too close to be a meaningful clone
                    # Normalize direction so A->B and B->A vote together.
                    if (dvec[0], dvec[1]) < (-dvec[0], -dvec[1]):
                        dvec = -dvec
                    key = (int(dvec[0] // offset_bin), int(dvec[1] // offset_bin))
                    offset_votes[key] = offset_votes.get(key, 0) + 1
                    cloned_pairs += 1
                    break

            total = max(len(keypoints), 1)
            # Strongest single coherent translation cluster.
            best_offset_support = max(offset_votes.values(), default=0)
            coherent_ratio = best_offset_support / total

            details["keypoints"] = len(keypoints)
            details["cloned_pairs"] = cloned_pairs
            details["coherent_cluster"] = best_offset_support
            details["coherent_ratio"] = round(coherent_ratio, 4)

            # Score is driven by the coherent cluster, NOT raw match count. This
            # ignores scattered text repetition while catching real cloning.
            score = min(coherent_ratio * 12.0, 1.0)
            if best_offset_support >= 12 and coherent_ratio > 0.03:
                score = max(score, 0.6)
                reasons.append(
                    "A coherent block of duplicated regions shares the same offset "
                    "(possible copy-move/cloning)."
                )
        else:
            details["keypoints"] = 0 if descriptors is None else len(keypoints)

        if not reasons:
            reasons.append("No significant duplicated regions detected.")

    except Exception as exc:  # noqa: BLE001
        score = 0.0
        reasons = [f"Copy-move analysis skipped: {exc}"]

    return {
        "name": "copy_move",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
    }
