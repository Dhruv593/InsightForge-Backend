"""Add user credits and assignable admin access."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0016"
down_revision = "20260922_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("credits", sa.Integer(), server_default="5", nullable=False))
    op.add_column("users", sa.Column("admin_access", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_check_constraint("ck_users_credits_nonnegative", "users", "credits >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_users_credits_nonnegative", "users", type_="check")
    op.drop_column("users", "admin_access")
    op.drop_column("users", "credits")
