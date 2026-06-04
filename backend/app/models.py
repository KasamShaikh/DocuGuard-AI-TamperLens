from datetime import datetime, timezone
import uuid

from sqlalchemy import String, Float, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Analysis(Base):
    __tablename__ = "analyses"

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    doc_type: Mapped[str] = mapped_column(String(64), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    file_uri: Mapped[str] = mapped_column(Text, default="")
    overlay_uri: Mapped[str] = mapped_column(Text, default="")

    detector_scores: Mapped[str] = mapped_column(Text, default="{}")  # json
    ocr_summary: Mapped[str] = mapped_column(Text, default="{}")  # json
    tamper_score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    llm_summary: Mapped[str] = mapped_column(Text, default="{}")  # json
    error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
