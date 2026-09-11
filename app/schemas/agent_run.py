from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID
    agent_name: str
    provider: str
    model: str
    status: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    total: int
