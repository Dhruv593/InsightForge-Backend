from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ux_reports_analysis_run_id", "analysis_run_id", unique=True),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings: Mapped[list[dict[str, Any]]] = mapped_column("key_findings_json", JSONB, nullable=False)
    statistical_findings: Mapped[list[str]] = mapped_column("statistical_findings_json", JSONB, nullable=False)
    data_notes: Mapped[list[str]] = mapped_column("data_notes_json", JSONB, nullable=False)
    limitations: Mapped[list[str]] = mapped_column("limitations_json", JSONB, nullable=False)
    recommendations: Mapped[list[str]] = mapped_column("recommendations_json", JSONB, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column("report_json", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="report")
