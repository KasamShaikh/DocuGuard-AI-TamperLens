"""Tier 1 — document-native forensics for PDF files.

Most banking / KYC / claims documents are PDFs. Unlike pixel forensics, a PDF
carries a verifiable digital provenance trail: object/xref structure, the
incremental-update history, producer/creator metadata, and embedded XMP. Genuine
single-pass exports look very different from files that were opened in an editor
and re-saved, or where text was rasterised over to hide an edit.

This detector is CPU-only and needs no model. It returns a soft-to-strong score
with human-readable reasons, and is a no-op (neutral) for non-PDF inputs.
"""
from __future__ import annotations

import io
import re


def _producer_looks_like_editor(producer: str, creator: str) -> bool:
    """Heuristic: editing tools (vs. straight generators) in producer/creator."""
    editors = (
        "acrobat", "photoshop", "illustrator", "gimp", "inkscape", "foxit",
        "pdf-xchange", "nitro", "pdfescape", "sejda", "ilovepdf", "smallpdf",
        "soda pdf", "pdfelement", "master pdf",
    )
    blob = f"{producer} {creator}".lower()
    return any(e in blob for e in editors)


def run(file_bytes: bytes, content_type: str = "") -> dict:
    reasons: list[str] = []
    details: dict = {}
    score = 0.0

    is_pdf = content_type == "application/pdf" or file_bytes[:5] == b"%PDF-"
    if not is_pdf:
        return {
            "name": "pdf_forensics",
            "score": 0.0,
            "reasons": ["Not a PDF — document-structure forensics not applicable."],
            "details": {"is_pdf": False},
        }

    try:
        import pikepdf
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "pdf_forensics",
            "score": 0.0,
            "reasons": [f"PDF forensics unavailable (pikepdf not installed): {exc}"],
            "details": {"is_pdf": True},
        }

    try:
        # --- Incremental-update history (multiple xref sections) ---
        # Each save appends a new "startxref"/"%%EOF". A pristine single export
        # has one; re-edited/re-saved PDFs accumulate several.
        raw = file_bytes
        eof_count = raw.count(b"%%EOF")
        startxref_count = raw.count(b"startxref")
        details["eof_markers"] = eof_count
        details["startxref_markers"] = startxref_count
        if eof_count >= 3 or startxref_count >= 3:
            score = max(score, 0.55)
            reasons.append(
                f"PDF was saved {max(eof_count, startxref_count)} times "
                "(multiple incremental updates) — consistent with post-creation "
                "editing."
            )
        elif eof_count == 2 or startxref_count == 2:
            score = max(score, 0.3)
            reasons.append(
                "PDF has one incremental update beyond the original save "
                "(e.g. annotation, form fill, or a minor edit)."
            )

        with pikepdf.open(io.BytesIO(raw)) as pdf:
            docinfo = {str(k): str(v) for k, v in (pdf.docinfo or {}).items()}
            producer = docinfo.get("/Producer", "")
            creator = docinfo.get("/Creator", "")
            details["producer"] = producer
            details["creator"] = creator
            details["pages"] = len(pdf.pages)

            if _producer_looks_like_editor(producer, creator):
                score = max(score, 0.45)
                reasons.append(
                    f"Producer/creator indicates an editing tool "
                    f"(producer={producer!r}, creator={creator!r}). Genuine "
                    "system-generated documents are usually produced by a "
                    "reporting/print engine, not an image/PDF editor."
                )

            # --- XMP vs docinfo metadata consistency ---
            try:
                with pdf.open_metadata() as meta:
                    xmp_producer = str(meta.get("pdf:Producer", "")) if meta else ""
                if xmp_producer and producer and xmp_producer not in producer \
                        and producer not in xmp_producer:
                    score = max(score, 0.4)
                    reasons.append(
                        "XMP and document-info producer disagree "
                        f"(xmp={xmp_producer!r} vs info={producer!r}) — a common "
                        "side effect of editing one layer but not the other."
                    )
            except Exception:  # noqa: BLE001
                pass

            # --- Rasterised-over-text heuristic ---
            # A page that is essentially one full-page image with little/no real
            # text often means the original text was flattened to hide an edit.
            page = pdf.pages[0]
            text_ops = 0
            image_xobjects = 0
            try:
                resources = page.get("/Resources", {})
                xobjs = resources.get("/XObject", {}) if resources else {}
                for _, xobj in (xobjs or {}).items():
                    if str(xobj.get("/Subtype", "")) == "/Image":
                        image_xobjects += 1
                content = page.get("/Contents")
                stream = bytes(content.read_bytes()) if content is not None else b""
                text_ops = stream.count(b"Tj") + stream.count(b"TJ")
            except Exception:  # noqa: BLE001
                pass
            details["page1_text_ops"] = text_ops
            details["page1_image_xobjects"] = image_xobjects
            if image_xobjects >= 1 and text_ops <= 2:
                score = max(score, 0.5)
                reasons.append(
                    "Page is image-dominant with almost no text operators — the "
                    "document may have been flattened/rasterised (text converted "
                    "to a picture), which can conceal edits from text inspection."
                )

        if not reasons:
            reasons.append(
                "PDF structure looks like a clean single-pass export "
                "(one save, no editor signature, consistent metadata)."
            )

    except Exception as exc:  # noqa: BLE001
        score = 0.0
        reasons = [f"PDF structure analysis skipped: {exc}"]

    return {
        "name": "pdf_forensics",
        "score": round(float(score), 3),
        "reasons": reasons,
        "details": details,
    }
