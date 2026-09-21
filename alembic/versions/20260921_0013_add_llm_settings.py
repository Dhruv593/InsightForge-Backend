"""Add the system-wide, admin-controlled LLM provider selection."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_0013"
down_revision = "20260918_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_llm_settings_singleton"),
        sa.CheckConstraint("provider IN ('gemini', 'groq')", name="ck_llm_settings_provider"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("llm_settings")
