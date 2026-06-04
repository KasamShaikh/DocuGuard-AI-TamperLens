import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..extractors import metadata as ex_metadata
from ..extractors import compression as ex_compression
from ..extractors import copy_move as ex_copy_move
from ..extractors import ai_generation as ex_ai
from ..extractors import content_consistency as ex_content
from ..extractors import pdf_forensics as ex_pdf
from ..extractors import id_checksums as ex_ids
from ..extractors.aggregate import aggregate
from ..models import Analysis
from ..storage import storage_service
from . import document_intelligence, foundry


def _render_pdf_first_page(file_bytes: bytes) -> bytes | None:
    """Render page 1 of a PDF to PNG bytes so pixel detectors can run.

    Returns None if rendering is unavailable or fails (pipeline still proceeds
    with document-native + OCR detectors).
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if doc.page_count == 0:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
    except Exception:  # noqa: BLE001
        return None


def run_analysis(
    analysis_id: str, file_bytes: bytes, db: Session, content_type: str = ""
) -> None:
    """Full pipeline: document-native + pixel + OCR detectors -> aggregate ->
    LLM summary -> persist.

    Handles both PDFs and images. For PDFs, page 1 is rendered to an image so
    pixel detectors still apply. Designed to run as a background task.
    """
    row = db.get(Analysis, analysis_id)
    if row is None:
        return

    try:
        row.status = "processing"
        db.commit()

        is_pdf = content_type == "application/pdf" or file_bytes[:5] == b"%PDF-"

        # Pixel detectors operate on a raster image. For PDFs, render page 1.
        if is_pdf:
            image_bytes = _render_pdf_first_page(file_bytes) or b""
        else:
            image_bytes = file_bytes

        # 1. Tier 1 — document-native forensics (PDF structure / provenance).
        pdf_res = ex_pdf.run(file_bytes, content_type)

        # 2. Classical pixel detectors (only when we have a raster image).
        if image_bytes:
            meta_res = ex_metadata.run(image_bytes)
            comp_res = ex_compression.run(image_bytes)
            clone_res = ex_copy_move.run(image_bytes)
            ai_res = ex_ai.run(image_bytes)

            heatmap = comp_res.pop("heatmap_png", None)
            if heatmap:
                row.overlay_uri = storage_service.save(heatmap, ".png", "image/png")
        else:
            meta_res = {"name": "metadata", "score": 0.0, "reasons": ["No raster image to analyze."], "details": {}}
            comp_res = {"name": "compression_ela", "score": 0.0, "reasons": ["No raster image to analyze."], "details": {}}
            clone_res = {"name": "copy_move", "score": 0.0, "reasons": ["No raster image to analyze."], "details": {}}
            ai_res = {"name": "ai_generation", "score": 0.0, "reasons": ["No raster image to analyze."], "details": {}}

        # 3. OCR / document understanding — DocIntel accepts PDF or image bytes.
        ocr = document_intelligence.extract(file_bytes if is_pdf else image_bytes)

        # 4. Tier 3 — content/figure consistency + identifier checksums.
        content_res = ex_content.run(ocr)
        ids_res = ex_ids.run(ocr)

        # 5. Tier 4 — multimodal vision judge (optional; independent visual
        # reasoning over the rendered page).
        vision_res = foundry.vision_judge(image_bytes, "image/png") if image_bytes else {
            "name": "vision_judge", "score": 0.0,
            "reasons": ["No raster image to analyze."], "details": {"enabled": False},
        }

        detectors = [
            pdf_res, meta_res, comp_res, clone_res, ai_res,
            content_res, ids_res, vision_res,
        ]

        # 6. Aggregate into combined score + decision.
        agg = aggregate(detectors)

        # 7. Build evidence and get LLM (or fallback) summary.
        evidence = {
            "detectors": detectors,
            "aggregate": agg,
            "ocr": {
                "available": ocr.get("available", False),
                "fields": ocr.get("fields", {}),
                "text_excerpt": (ocr.get("text", "") or "")[:1500],
            },
        }
        llm_summary = foundry.summarize(evidence)

        # 8. Persist results.
        row.detector_scores = json.dumps({"detectors": detectors, "aggregate": agg})
        row.ocr_summary = json.dumps(
            {k: v for k, v in ocr.items() if k != "text"} | {"text_len": len(ocr.get("text", ""))}
        )
        row.tamper_score = agg["tamper_score"]
        row.decision = agg["decision"]
        row.llm_summary = json.dumps(llm_summary)
        row.status = "completed"
        row.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        row = db.get(Analysis, analysis_id)
        if row is not None:
            row.status = "failed"
            row.error = str(exc)
            row.completed_at = datetime.now(timezone.utc)
            db.commit()
