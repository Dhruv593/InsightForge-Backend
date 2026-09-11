from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.analysis_task import AnalysisTask
    from app.models.statistical_validation import StatisticalValidation
    from app.models.claim import Claim
from app.models.claim_evidence import claim_evidence


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_analysis_run_id", "analysis_run_id"),
        Index("ix_evidence_analysis_task_id", "analysis_task_id"),
        Index("ux_evidence_run_code", "analysis_run_id", "evidence_code", unique=True),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_tasks.id", ondelete="CASCADE"), nullable=False)
    evidence_code: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    columns_used: Mapped[list[str]] = mapped_column("columns_used_json", JSONB, nullable=False)
    filters: Mapped[list[dict[str, Any]]] = mapped_column("filters_json", JSONB, nullable=False)
    operation: Mapped[dict[str, Any]] = mapped_column("operation_json", JSONB, nullable=False)
    result: Mapped[dict[str, Any] | list[Any]] = mapped_column("result_json", JSONB, nullable=False)
    interpretation: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[list[str]] = mapped_column("limitations_json", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="evidence_items")
    analysis_task: Mapped["AnalysisTask"] = relationship(back_populates="evidence_items")
    statistical_validations: Mapped[list["StatisticalValidation"]] = relationship(back_populates="evidence", passive_deletes=True)
    claims: Mapped[list["Claim"]] = relationship(secondary=claim_evidence, back_populates="evidence_items", lazy="selectin")
