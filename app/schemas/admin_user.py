from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AdminUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    is_active: bool
    is_email_verified: bool
    is_admin: bool
    admin_access: bool
    admin_managed_by_environment: bool
    credits: int
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int


class AdminAccessUpdate(BaseModel):
    is_admin: bool


class CreditAdjustment(BaseModel):
    delta: int = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=3, max_length=240)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Credit adjustment reason must contain at least three characters.")
        return normalized

    @model_validator(mode="after")
    def reject_zero(self):
        if self.delta == 0:
            raise ValueError("Credit adjustment must not be zero.")
        return self
