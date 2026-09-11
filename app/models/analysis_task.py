from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.analysis_constants import AnalysisTaskStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_plan import AnalysisPlan
    from app.models.evidence import Evidence
    from app.models.statistical_validation import StatisticalValidation


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    __table_args__ = (
        CheckConstraint("analysis_type IN ('aggregation', 'comparison', 'segmentation', 'correlation', 'statistical_test', 'regression', 'time_series', 'distribution', 'data_quality')", name="ck_analysis_tasks_type"),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'skipped')", name="ck_analysis_tasks_status"),
        CheckConstraint("priority > 0", name="ck_analysis_tasks_priority"),
        Index("ix_analysis_tasks_analysis_plan_id", "analysis_plan_id"),
        Index("ux_analysis_tasks_plan_code", "analysis_plan_id", "task_code", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_plan_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_plans.id", ondelete="CASCADE"), nullable=False)
    task_code: Mapped[str] = mapped_column(String(32), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    required_columns: Mapped[list[str]] = mapped_column("required_columns_json", JSONB, nullable=False)
    depends_on: Mapped[list[str]] = mapped_column("depends_on_json", JSONB, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AnalysisTaskStatus.PENDING.value, server_default=AnalysisTaskStatus.PENDING.value)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    analysis_plan: Mapped["AnalysisPlan"] = relationship(back_populates="tasks")
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="analysis_task", cascade="all, delete-orphan", passive_deletes=True)
    statistical_validations: Mapped[list["StatisticalValidation"]] = relationship(back_populates="analysis_task", cascade="all, delete-orphan", passive_deletes=True)
