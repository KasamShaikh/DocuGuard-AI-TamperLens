from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AnalyzeAccepted(BaseModel):
    analysis_id: str
    status: str


class AnalysisResult(BaseModel):
    analysis_id: str
    doc_type: str
    status: str
    file_uri: str
    overlay_uri: str
    detector_scores: dict[str, Any]
    ocr_summary: dict[str, Any]
    tamper_score: float
    decision: str
    llm_summary: dict[str, Any]
    error: str
    created_at: datetime | None
    completed_at: datetime | None
