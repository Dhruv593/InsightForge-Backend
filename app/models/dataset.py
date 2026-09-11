from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.analysis_run import AnalysisRun
    from app.models.conversation import Conversation
    from app.models.dataset_profile import DatasetProfile
    from app.models.user import User


class DatasetUploadStatus(str, Enum):
    UPLOADED = "uploaded"
    FAILED = "failed"


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint(
            "upload_status IN ('uploaded', 'failed')",
            name="ck_datasets_upload_status",
        ),
        Index("ix_datasets_user_id", "user_id"),
        Index("ix_datasets_created_at", "created_at"),
        Index(
            "ux_datasets_cloudinary_public_id",
            "cloudinary_public_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cloudinary_url: Mapped[str] = mapped_column(Text, nullable=False)
    cloudinary_public_id: Mapped[str] = mapped_column(String(512), nullable=False)
    cloudinary_resource_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="raw",
        server_default="raw",
    )
    upload_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DatasetUploadStatus.UPLOADED.value,
        server_default=DatasetUploadStatus.UPLOADED.value,
    )
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

    user: Mapped["User"] = relationship(back_populates="datasets")
    profile: Mapped["DatasetProfile | None"] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True,
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True,
    )
