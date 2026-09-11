from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.analysis_constants import AnalysisPlanStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.analysis_task import AnalysisTask


class AnalysisPlan(Base):
    __tablename__ = "analysis_plans"
    __table_args__ = (
        CheckConstraint("status IN ('created', 'validated', 'failed')", name="ck_analysis_plans_status"),
        Index("ux_analysis_plans_analysis_run_id", "analysis_run_id", unique=True),
        Index("ix_analysis_plans_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    target_metric: Mapped[str | None] = mapped_column(String(255), nullable=True)
    analysis_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    requires_statistics: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_visualization: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completion_criteria: Mapped[list[str]] = mapped_column("completion_criteria_json", JSONB, nullable=False, default=list)
    limitations: Mapped[list[str]] = mapped_column("limitations_json", JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AnalysisPlanStatus.CREATED.value, server_default=AnalysisPlanStatus.CREATED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="analysis_plan")
    tasks: Mapped[list["AnalysisTask"]] = relationship(
        back_populates="analysis_plan", cascade="all, delete-orphan",
        passive_deletes=True, order_by="AnalysisTask.priority, AnalysisTask.task_code",
    )
