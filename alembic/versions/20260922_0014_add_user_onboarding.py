"""Track completion of the first-time product tour."""
from alembic import op
import sqlalchemy as sa

revision = "20260922_0014"
down_revision = "20260921_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    # Accounts created before the tour existed should not receive first-time onboarding.
    op.execute("UPDATE users SET onboarding_completed_at = now()")


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
