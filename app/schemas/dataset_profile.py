from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DatasetProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_id: UUID
    profile_status: str
    profile_version: int
    row_count: int | None
    column_count: int | None
    schema: dict[str, Any] = Field(validation_alias="schema_json")
    missing_values: dict[str, Any] = Field(
        validation_alias="missing_values_json",
    )
    duplicate_summary: dict[str, Any] = Field(
        validation_alias="duplicate_summary_json",
    )
    numeric_summary: dict[str, Any] = Field(
        validation_alias="numeric_summary_json",
    )
    categorical_summary: dict[str, Any] = Field(
        validation_alias="categorical_summary_json",
    )
    date_summary: dict[str, Any] = Field(validation_alias="date_summary_json")
    outlier_summary: dict[str, Any] = Field(
        validation_alias="outlier_summary_json",
    )
    quality_issues: list[dict[str, Any]] = Field(
        validation_alias="quality_issues_json",
    )
    profiled_at: datetime | None
    created_at: datetime
    updated_at: datetime
