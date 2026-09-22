from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account_token import AccountToken
    from app.models.analysis_run import AnalysisRun
    from app.models.conversation import Conversation
    from app.models.dataset import Dataset
    from app.models.user_session import UserSession
    from app.models.payment_order import PaymentOrder


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_email", "email"),
        CheckConstraint("credits >= 0", name="ck_users_credits_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    admin_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    datasets: Mapped[list["Dataset"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
    )
    account_tokens: Mapped[list["AccountToken"]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    payment_orders: Mapped[list["PaymentOrder"]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def is_admin(self) -> bool:
        from app.core.config import get_settings
        allowed = {item.strip().lower() for item in get_settings().admin_emails.split(",") if item.strip()}
        return self.is_active and self.is_email_verified and (self.admin_access or self.email.lower() in allowed)

    @property
    def admin_managed_by_environment(self) -> bool:
        from app.core.config import get_settings
        allowed = {item.strip().lower() for item in get_settings().admin_emails.split(",") if item.strip()}
        return self.email.lower() in allowed

    @property
    def password_configured(self) -> bool:
        return bool(self.password_hash)
