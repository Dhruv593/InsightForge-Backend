"""add evidence and statistical validations

Revision ID: 20260831_0007
Revises: 20260831_0006
Create Date: 2026-08-31
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0007"
down_revision: str | None = "20260831_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_tasks", sa.Column("status_reason", sa.Text(), nullable=True))
    op.drop_constraint("ck_analysis_tasks_status", "analysis_tasks", type_="check")
    op.create_check_constraint("ck_analysis_tasks_status", "analysis_tasks", "status IN ('pending', 'running', 'completed', 'failed', 'skipped')")
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_task_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_code", sa.String(64), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("columns_used_json", postgresql.JSONB(), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(), nullable=False),
        sa.Column("operation_json", postgresql.JSONB(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=False),
        sa.Column("limitations_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_task_id"], ["analysis_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_analysis_run_id", "evidence", ["analysis_run_id"])
    op.create_index("ix_evidence_analysis_task_id", "evidence", ["analysis_task_id"])
    op.create_index("ux_evidence_run_code", "evidence", ["analysis_run_id", "evidence_code"], unique=True)
    op.create_table(
        "statistical_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_task_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("method_requested", sa.String(255), nullable=False),
        sa.Column("method_used", sa.String(64), nullable=False),
        sa.Column("assumptions_json", postgresql.JSONB(), nullable=False),
        sa.Column("p_value", sa.Float(), nullable=True),
        sa.Column("effect_size", sa.Float(), nullable=True),
        sa.Column("confidence_interval_json", postgresql.JSONB(), nullable=True),
        sa.Column("is_significant", sa.Boolean(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_task_id"], ["analysis_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_statistical_validations_analysis_run_id", "statistical_validations", ["analysis_run_id"])
    op.create_index("ix_statistical_validations_analysis_task_id", "statistical_validations", ["analysis_task_id"])
    op.create_index("ix_statistical_validations_evidence_id", "statistical_validations", ["evidence_id"])


def downgrade() -> None:
    op.drop_table("statistical_validations")
    op.drop_table("evidence")
    op.drop_constraint("ck_analysis_tasks_status", "analysis_tasks", type_="check")
    op.execute("UPDATE analysis_tasks SET status = 'pending' WHERE status <> 'pending'")
    op.create_check_constraint("ck_analysis_tasks_status", "analysis_tasks", "status = 'pending'")
    op.drop_column("analysis_tasks", "status_reason")
