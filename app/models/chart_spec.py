from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun


class ChartSpec(Base):
    __tablename__ = "chart_specs"
    __table_args__ = (
        CheckConstraint("chart_type IN ('line','bar','horizontal_bar','grouped_bar','stacked_bar','scatter','histogram','boxplot','pie','donut','heatmap','waterfall')", name="ck_chart_specs_type"),
        Index("ix_chart_specs_analysis_run_id", "analysis_run_id"),
        Index("ux_chart_specs_run_code", "analysis_run_id", "chart_code", unique=True),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    analysis_run_id: Mapped[UUID] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    chart_code: Mapped[str] = mapped_column(String(16), nullable=False)
    chart_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    x_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    y_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_codes: Mapped[list[str]] = mapped_column("evidence_codes_json", JSONB, nullable=False)
    filters: Mapped[list[dict[str, Any]]] = mapped_column("filters_json", JSONB, nullable=False)
    chart_config: Mapped[dict[str, Any]] = mapped_column("chart_config_json", JSONB, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    analysis_run: Mapped["AnalysisRun"] = relationship(back_populates="chart_specs")
