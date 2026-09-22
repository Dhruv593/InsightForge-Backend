from datetime import datetime
from uuid import UUID

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_file_name: str
    stored_file_name: str
    file_type: str
    mime_type: str
    file_size: int
    cloudinary_resource_type: str
    upload_status: str
    created_at: datetime
    updated_at: datetime


class DatasetListResponse(BaseModel):
    items: list[DatasetResponse]
    total: int


class DatasetDeleteResponse(BaseModel):
    status: str = "deleted"


class DatasetPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    returned_rows: int
    offset: int
    truncated: bool
    warnings: list[str] = Field(default_factory=list)
