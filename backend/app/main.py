import json
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, get_db, init_db
from .models import Analysis
from .schemas import AnalysisResult, AnalyzeAccepted
from .services.analysis import run_analysis, run_second_opinion
from .storage import storage_service

logger = logging.getLogger("docuguard.api")

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/tiff", "image/webp", "application/pdf",
}


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "storage_mode": storage_service.mode,
        "docintel_configured": bool(settings.docintel_endpoint),
        "foundry_configured": bool(settings.foundry_endpoint),
    }


def _process_in_background(analysis_id: str, image_bytes: bytes, content_type: str) -> None:
    # Background tasks get their own DB session (request session is closed).
    db = SessionLocal()
    try:
        run_analysis(analysis_id, image_bytes, db, content_type)
    finally:
        db.close()


@app.post("/api/analyze", response_model=AnalyzeAccepted, status_code=202)
async def analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: str = Form("unknown"),
    db: Session = Depends(get_db),
) -> AnalyzeAccepted:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

    image_bytes = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit.")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        suffix = "." + (file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "bin")
        file_uri = storage_service.save(image_bytes, suffix, file.content_type)

        row = Analysis(doc_type=doc_type, status="pending", file_uri=file_uri)
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Failed to persist upload for analysis.")
        raise HTTPException(
            status_code=500, detail=f"Failed to accept upload: {exc}"
        ) from exc

    background_tasks.add_task(_process_in_background, row.analysis_id, image_bytes, file.content_type)
    return AnalyzeAccepted(analysis_id=row.analysis_id, status=row.status)


@app.get("/api/analyze/{analysis_id}", response_model=AnalysisResult)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisResult:
    row = db.get(Analysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")

    return _to_result(row)


@app.post("/api/analyze/{analysis_id}/second-opinion", response_model=AnalysisResult)
def second_opinion(analysis_id: str, db: Session = Depends(get_db)) -> AnalysisResult:
    """Run the AI multimodal vision judge on demand for a single document.

    This is the user-triggered "get a second opinion" action. It works even when
    the global vision judge is disabled, but requires a configured Foundry /
    OpenAI endpoint.
    """
    row = db.get(Analysis, analysis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    if row.status != "completed":
        raise HTTPException(status_code=409, detail="Analysis is not completed yet.")
    if not settings.foundry_endpoint:
        raise HTTPException(
            status_code=400,
            detail="AI second opinion is unavailable: no Foundry / OpenAI endpoint configured.",
        )

    try:
        run_second_opinion(analysis_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Second-opinion analysis failed.")
        raise HTTPException(status_code=500, detail=f"Second opinion failed: {exc}") from exc

    db.refresh(row)
    return _to_result(row)


def _to_result(row: Analysis) -> AnalysisResult:
    return AnalysisResult(
        analysis_id=row.analysis_id,
        doc_type=row.doc_type,
        status=row.status,
        file_uri=row.file_uri,
        overlay_uri=row.overlay_uri,
        detector_scores=json.loads(row.detector_scores or "{}"),
        ocr_summary=json.loads(row.ocr_summary or "{}"),
        tamper_score=row.tamper_score,
        decision=row.decision,
        llm_summary=json.loads(row.llm_summary or "{}"),
        error=row.error,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )
