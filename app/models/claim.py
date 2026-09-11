from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.claim_evidence import claim_evidence

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.claim_review import ClaimReview
    from app.models.evidence import Evidence


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("claim_type IN ('descriptive','comparative','diagnostic','statistical','relationship','limitation')", name="ck_claims_type"),
        CheckConstraint("status IN ('pending_review','accepted','rejected','needs_more_evidence')", name="ck_claims_status"),
        Index("ix_claims_analysis_run_id", "analysis_run_id"),
        Index("ux_claims_run_code", "analysis_run_id", "claim_code", unique=True),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    claim_code: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review", server_default="pending_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="claims")
    evidence_items: Mapped[list["Evidence"]] = relationship(secondary=claim_evidence, back_populates="claims", lazy="selectin")
    review: Mapped["ClaimReview | None"] = relationship(back_populates="claim", cascade="all, delete-orphan", passive_deletes=True, uselist=False)
