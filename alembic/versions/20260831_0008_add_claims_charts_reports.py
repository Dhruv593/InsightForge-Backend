"""add claims charts and reports

Revision ID: 20260831_0008
Revises: 20260831_0007
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0008"
down_revision: str | None = "20260831_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("claims",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("claim_code", sa.String(16), nullable=False), sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False), sa.Column("status", sa.String(32), server_default="pending_review", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("claim_type IN ('descriptive','comparative','diagnostic','statistical','relationship','limitation')", name="ck_claims_type"),
        sa.CheckConstraint("status IN ('pending_review','accepted','rejected','needs_more_evidence')", name="ck_claims_status"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_claims_analysis_run_id", "claims", ["analysis_run_id"])
    op.create_index("ux_claims_run_code", "claims", ["analysis_run_id", "claim_code"], unique=True)
    op.create_table("claim_evidence",
        sa.Column("claim_id", sa.Uuid(), nullable=False), sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id"))
    op.create_table("claim_reviews",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("claim_id", sa.Uuid(), nullable=False), sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("evidence_strength", sa.String(16), nullable=False),
        sa.Column("issues_json", postgresql.JSONB(), nullable=False), sa.Column("missing_analysis_json", postgresql.JSONB(), nullable=False),
        sa.Column("corrected_wording", sa.Text(), nullable=True), sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('accepted','rejected','needs_more_evidence')", name="ck_claim_reviews_status"),
        sa.CheckConstraint("evidence_strength IN ('weak','moderate','strong')", name="ck_claim_reviews_strength"),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ux_claim_reviews_claim_id", "claim_reviews", ["claim_id"], unique=True)
    op.create_index("ix_claim_reviews_analysis_run_id", "claim_reviews", ["analysis_run_id"])
    op.create_table("chart_specs",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("chart_code", sa.String(16), nullable=False), sa.Column("chart_type", sa.String(32), nullable=False), sa.Column("title", sa.String(300), nullable=False),
        sa.Column("x_column", sa.String(255), nullable=True), sa.Column("y_column", sa.String(255), nullable=True), sa.Column("group_column", sa.String(255), nullable=True),
        sa.Column("evidence_codes_json", postgresql.JSONB(), nullable=False), sa.Column("filters_json", postgresql.JSONB(), nullable=False),
        sa.Column("chart_config_json", postgresql.JSONB(), nullable=False), sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("chart_type IN ('line','bar','horizontal_bar','grouped_bar','stacked_bar','scatter','histogram','boxplot','pie','donut','heatmap','waterfall')", name="ck_chart_specs_type"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_chart_specs_analysis_run_id", "chart_specs", ["analysis_run_id"])
    op.create_index("ux_chart_specs_run_code", "chart_specs", ["analysis_run_id", "chart_code"], unique=True)
    op.create_table("reports",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False), sa.Column("key_findings_json", postgresql.JSONB(), nullable=False),
        sa.Column("statistical_findings_json", postgresql.JSONB(), nullable=False), sa.Column("data_notes_json", postgresql.JSONB(), nullable=False),
        sa.Column("limitations_json", postgresql.JSONB(), nullable=False), sa.Column("recommendations_json", postgresql.JSONB(), nullable=False),
        sa.Column("report_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ux_reports_analysis_run_id", "reports", ["analysis_run_id"], unique=True)


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("chart_specs")
    op.drop_table("claim_reviews")
    op.drop_table("claim_evidence")
    op.drop_table("claims")
