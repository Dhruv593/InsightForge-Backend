from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.analysis_constants import AnalysisRunStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent_run import AgentRun
    from app.models.analysis_plan import AnalysisPlan
    from app.models.evidence import Evidence
    from app.models.statistical_validation import StatisticalValidation
    from app.models.conversation import Conversation
    from app.models.dataset import Dataset
    from app.models.message import Message
    from app.models.user import User
    from app.models.claim import Claim
    from app.models.claim_review import ClaimReview
    from app.models.chart_spec import ChartSpec
    from app.models.report import Report


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("llm_provider IN ('gemini', 'groq', 'openai', 'anthropic')", name="ck_analysis_runs_provider"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_analysis_runs_status",
        ),
        Index("ix_analysis_runs_user_id", "user_id"),
        Index("ix_analysis_runs_dataset_id", "dataset_id"),
        Index("ix_analysis_runs_conversation_id", "conversation_id"),
        Index("ix_analysis_runs_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AnalysisRunStatus.PENDING.value, server_default=AnalysisRunStatus.PENDING.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="analysis_runs")
    dataset: Mapped["Dataset"] = relationship(back_populates="analysis_runs")
    conversation: Mapped["Conversation"] = relationship(back_populates="analysis_runs")
    messages: Mapped[list["Message"]] = relationship(back_populates="analysis_run", passive_deletes=True)
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    analysis_plan: Mapped["AnalysisPlan | None"] = relationship(
        back_populates="analysis_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    evidence_items: Mapped[list["Evidence"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True)
    statistical_validations: Mapped[list["StatisticalValidation"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True)
    claims: Mapped[list["Claim"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True)
    claim_reviews: Mapped[list["ClaimReview"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True)
    chart_specs: Mapped[list["ChartSpec"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True)
    report: Mapped["Report | None"] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True, uselist=False)
