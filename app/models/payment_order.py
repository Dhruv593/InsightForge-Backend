from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        CheckConstraint("credits > 0", name="ck_payment_orders_credits_positive"),
        CheckConstraint("amount_paise > 0", name="ck_payment_orders_amount_positive"),
        CheckConstraint("status IN ('pending', 'paid', 'failed')", name="ck_payment_orders_status"),
        Index("ix_payment_orders_user_id", "user_id"),
        Index("ix_payment_orders_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(160), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default="INR")
    receipt: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    razorpay_order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="payment_orders")
