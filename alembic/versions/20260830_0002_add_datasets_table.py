"""add datasets table

Revision ID: 20260830_0002
Revises: 20260830_0001
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260830_0002"
down_revision: str | None = "20260830_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("original_file_name", sa.String(length=255), nullable=False),
        sa.Column("stored_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("cloudinary_url", sa.Text(), nullable=False),
        sa.Column("cloudinary_public_id", sa.String(length=512), nullable=False),
        sa.Column(
            "cloudinary_resource_type",
            sa.String(length=32),
            server_default="raw",
            nullable=False,
        ),
        sa.Column(
            "upload_status",
            sa.String(length=16),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "upload_status IN ('uploaded', 'failed')",
            name="ck_datasets_upload_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_datasets_created_at",
        "datasets",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_datasets_user_id",
        "datasets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ux_datasets_cloudinary_public_id",
        "datasets",
        ["cloudinary_public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_datasets_cloudinary_public_id",
        table_name="datasets",
    )
    op.drop_index("ix_datasets_user_id", table_name="datasets")
    op.drop_index("ix_datasets_created_at", table_name="datasets")
    op.drop_table("datasets")
