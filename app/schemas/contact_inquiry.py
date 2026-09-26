from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ContactInquiryStatus = Literal["new", "read", "replied", "closed"]


class ContactInquiryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    subject: str
    message: str
    status: ContactInquiryStatus
    notification_status: str
    reply_message: str | None
    replied_by: UUID | None
    replied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContactInquiryListResponse(BaseModel):
    items: list[ContactInquiryResponse]
    total: int
    counts: dict[str, int]


class ContactInquiryStatusUpdate(BaseModel):
    status: ContactInquiryStatus


class ContactInquiryReply(BaseModel):
    message: str = Field(min_length=2, max_length=10000)
