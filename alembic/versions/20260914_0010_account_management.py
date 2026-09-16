"""Add account verification and recovery tokens."""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0010"
down_revision = "20260911_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.alter_column("users", "is_email_verified", server_default=sa.false())
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_type", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("token_type IN ('email_verification', 'password_reset')", name="ck_account_tokens_type"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_account_tokens_hash", "account_tokens", ["token_hash"], unique=True)
    op.create_index("ix_account_tokens_user_type", "account_tokens", ["user_id", "token_type"])


def downgrade():
    op.drop_table("account_tokens")
    op.drop_column("users", "token_version")
    op.drop_column("users", "is_email_verified")
