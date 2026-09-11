"""add analysis plans and tasks

Revision ID: 20260831_0006
Revises: 20260831_0005
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0006"
down_revision: str | None = "20260831_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("question_type", sa.String(length=50), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("target_metric", sa.String(length=255), nullable=True),
        sa.Column("analysis_strategy", sa.Text(), nullable=False),
        sa.Column("requires_statistics", sa.Boolean(), nullable=False),
        sa.Column("requires_visualization", sa.Boolean(), nullable=False),
        sa.Column("completion_criteria_json", postgresql.JSONB(), nullable=False),
        sa.Column("limitations_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="created", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('created', 'validated', 'failed')", name="ck_analysis_plans_status"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_analysis_plans_analysis_run_id", "analysis_plans", ["analysis_run_id"], unique=True)
    op.create_index("ix_analysis_plans_created_at", "analysis_plans", ["created_at"])

    op.create_table(
        "analysis_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_plan_id", sa.Uuid(), nullable=False),
        sa.Column("task_code", sa.String(length=32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("analysis_type", sa.String(length=32), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("required_columns_json", postgresql.JSONB(), nullable=False),
        sa.Column("depends_on_json", postgresql.JSONB(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("analysis_type IN ('aggregation', 'comparison', 'segmentation', 'correlation', 'statistical_test', 'regression', 'time_series', 'distribution', 'data_quality')", name="ck_analysis_tasks_type"),
        sa.CheckConstraint("status = 'pending'", name="ck_analysis_tasks_status"),
        sa.CheckConstraint("priority > 0", name="ck_analysis_tasks_priority"),
        sa.ForeignKeyConstraint(["analysis_plan_id"], ["analysis_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_tasks_analysis_plan_id", "analysis_tasks", ["analysis_plan_id"])
    op.create_index("ux_analysis_tasks_plan_code", "analysis_tasks", ["analysis_plan_id", "task_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_analysis_tasks_plan_code", table_name="analysis_tasks")
    op.drop_index("ix_analysis_tasks_analysis_plan_id", table_name="analysis_tasks")
    op.drop_table("analysis_tasks")
    op.drop_index("ix_analysis_plans_created_at", table_name="analysis_plans")
    op.drop_index("ux_analysis_plans_analysis_run_id", table_name="analysis_plans")
    op.drop_table("analysis_plans")
