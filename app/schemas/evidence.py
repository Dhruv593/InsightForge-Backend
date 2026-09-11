from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_run_id: UUID
    analysis_task_id: UUID
    evidence_code: str
    method: str
    columns_used: list[str]
    filters: list[dict[str, Any]]
    operation: dict[str, Any]
    result: dict[str, Any] | list[Any]
    interpretation: str
    limitations: list[str]
    created_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceResponse]
    total: int
