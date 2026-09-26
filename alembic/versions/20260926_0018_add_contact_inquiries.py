"""Persist and manage landing-page contact inquiries."""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0018"
down_revision = "20260922_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_inquiries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="new", nullable=False),
        sa.Column("notification_status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("reply_message", sa.Text(), nullable=True),
        sa.Column("replied_by", sa.Uuid(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('new', 'read', 'replied', 'closed')", name="ck_contact_inquiries_status"),
        sa.CheckConstraint("notification_status IN ('pending', 'sent', 'failed', 'not_configured')", name="ck_contact_inquiries_notification_status"),
        sa.ForeignKeyConstraint(["replied_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_inquiries_status_created_at", "contact_inquiries", ["status", "created_at"])
    op.create_index("ix_contact_inquiries_email", "contact_inquiries", ["email"])


def downgrade() -> None:
    op.drop_index("ix_contact_inquiries_email", table_name="contact_inquiries")
    op.drop_index("ix_contact_inquiries_status_created_at", table_name="contact_inquiries")
    op.drop_table("contact_inquiries")
