"""Support Google identities without inventing local passwords."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0009"
down_revision = "20260831_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column("users", sa.Column("google_subject", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_google_subject", "users", ["google_subject"])


def downgrade():
    # Refuse a destructive rollback while Google-only accounts still exist.
    if op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL")).scalar():
        raise RuntimeError("Cannot downgrade while Google-only accounts exist.")
    op.drop_constraint("uq_users_google_subject", "users", type_="unique")
    op.drop_column("users", "google_subject")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)
