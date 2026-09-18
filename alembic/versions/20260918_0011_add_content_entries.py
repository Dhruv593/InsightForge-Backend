"""Add generic site content entries for the landing-page CMS."""
from alembic import op
import sqlalchemy as sa

revision = "20260918_0011"
down_revision = "20260914_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), server_default="published", nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_type", "slug", name="uq_content_entries_type_slug"),
    )
    op.create_index("ix_content_entries_type_status", "content_entries", ["content_type", "status"])


def downgrade():
    op.drop_index("ix_content_entries_type_status", table_name="content_entries")
    op.drop_table("content_entries")
