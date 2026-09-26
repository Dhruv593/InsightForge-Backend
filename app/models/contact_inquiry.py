from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContactInquiry(Base):
    """A message submitted through the public landing-page contact form."""

    __tablename__ = "contact_inquiries"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'read', 'replied', 'closed')", name="ck_contact_inquiries_status"),
        CheckConstraint(
            "notification_status IN ('pending', 'sent', 'failed', 'not_configured')",
            name="ck_contact_inquiries_notification_status",
        ),
        Index("ix_contact_inquiries_status_created_at", "status", "created_at"),
        Index("ix_contact_inquiries_email", "email"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new", server_default="new")
    notification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    reply_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
