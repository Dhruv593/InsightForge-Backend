"""Add Razorpay payment orders for idempotent credit fulfillment."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0017"
down_revision = "20260922_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_name", sa.String(length=160), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("receipt", sa.String(length=40), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=100), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("credits > 0", name="ck_payment_orders_credits_positive"),
        sa.CheckConstraint("amount_paise > 0", name="ck_payment_orders_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'paid', 'failed')", name="ck_payment_orders_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt"),
        sa.UniqueConstraint("razorpay_order_id"),
        sa.UniqueConstraint("razorpay_payment_id"),
    )
    op.create_index("ix_payment_orders_user_id", "payment_orders", ["user_id"])
    op.create_index("ix_payment_orders_status", "payment_orders", ["status"])


def downgrade() -> None:
    op.drop_index("ix_payment_orders_status", table_name="payment_orders")
    op.drop_index("ix_payment_orders_user_id", table_name="payment_orders")
    op.drop_table("payment_orders")
