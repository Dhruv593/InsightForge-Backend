from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.claim import Claim


class ClaimReview(Base):
    __tablename__ = "claim_reviews"
    __table_args__ = (
        CheckConstraint("status IN ('accepted','rejected','needs_more_evidence')", name="ck_claim_reviews_status"),
        CheckConstraint("evidence_strength IN ('weak','moderate','strong')", name="ck_claim_reviews_strength"),
        Index("ux_claim_reviews_claim_id", "claim_id", unique=True),
        Index("ix_claim_reviews_analysis_run_id", "analysis_run_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_strength: Mapped[str] = mapped_column(String(16), nullable=False)
    issues: Mapped[list[str]] = mapped_column("issues_json", JSONB, nullable=False)
    missing_analysis: Mapped[list[str]] = mapped_column("missing_analysis_json", JSONB, nullable=False)
    corrected_wording: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claim: Mapped["Claim"] = relationship(back_populates="review")
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="claim_reviews")
