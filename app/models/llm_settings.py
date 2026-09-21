from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LLMSettings(Base):
    """One admin-controlled provider selection shared by all users."""

    __tablename__ = "llm_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_llm_settings_singleton"),
        CheckConstraint("provider IN ('gemini', 'groq')", name="ck_llm_settings_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
