from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.analysis_task import AnalysisTask
    from app.models.evidence import Evidence


class StatisticalValidation(Base):
    __tablename__ = "statistical_validations"
    __table_args__ = (
        Index("ix_statistical_validations_analysis_run_id", "analysis_run_id"),
        Index("ix_statistical_validations_analysis_task_id", "analysis_task_id"),
        Index("ix_statistical_validations_evidence_id", "evidence_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False)
    evidence_id: Mapped[UUID | None] = mapped_column(ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True)
    method_requested: Mapped[str] = mapped_column(String(255), nullable=False)
    method_used: Mapped[str] = mapped_column(String(64), nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column("assumptions_json", JSONB, nullable=False)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_interval: Mapped[dict[str, Any] | None] = mapped_column("confidence_interval_json", JSONB, nullable=True)
    is_significant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    warnings: Mapped[list[str]] = mapped_column("warnings_json", JSONB, nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="statistical_validations")
    analysis_task: Mapped["AnalysisTask"] = relationship(back_populates="statistical_validations")
    evidence: Mapped["Evidence | None"] = relationship(back_populates="statistical_validations")
