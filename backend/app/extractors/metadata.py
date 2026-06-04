import io

import exifread
from PIL import Image


# Software/tools that commonly indicate the image was edited after capture.
EDITOR_SIGNATURES = (
    "photoshop",
    "gimp",
    "lightroom",
    "paint.net",
    "pixelmator",
    "affinity",
    "snapseed",
    "facetune",
    "canva",
    "inkscape",
    "imagemagick",
)


def run(image_bytes: bytes) -> dict:
    """Inspect EXIF/metadata for editing fingerprints and inconsistencies."""
    reasons: list[str] = []
    score = 0.0
    details: dict = {}

    try:
        tags = exifread.process_file(io.BytesIO(image_bytes), details=False)
    except Exception:
        tags = {}

    software = str(tags.get("Image Software", "")).lower()
    details["software"] = software or None
    if any(sig in software for sig in EDITOR_SIGNATURES):
        score += 0.5
        reasons.append(f"Image software tag indicates editing tool: '{software}'.")

    has_datetime_original = "EXIF DateTimeOriginal" in tags
    has_datetime = "Image DateTime" in tags
    if has_datetime_original and has_datetime:
        if str(tags["EXIF DateTimeOriginal"]) != str(tags["Image DateTime"]):
            score += 0.2
            reasons.append("Capture timestamp differs from file modification timestamp.")

    has_camera = "Image Make" in tags or "Image Model" in tags
    details["camera_make"] = str(tags.get("Image Make", "")) or None
    details["camera_model"] = str(tags.get("Image Model", "")) or None

    # Determine format/structure cues.
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            details["format"] = img.format
            details["mode"] = img.mode
            details["size"] = list(img.size)
            has_exif_block = bool(getattr(img, "_getexif", lambda: None)())
    except Exception:
        has_exif_block = False
        details["format"] = None

    # Real camera captures usually carry EXIF + camera tags. A photo-format image
    # with no EXIF at all is a mild signal of re-saving/exporting after editing.
    if details.get("format") in {"JPEG", "TIFF"} and not has_camera and not has_exif_block:
        score += 0.25
        reasons.append("No camera/EXIF metadata present on a photo-format image (possible re-export).")

    score = min(score, 1.0)
    if not reasons:
        reasons.append("No metadata anomalies detected.")

    return {
        "name": "metadata",
        "score": round(score, 3),
        "reasons": reasons,
        "details": details,
    }
