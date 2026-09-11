from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.message import MessageResponse


class AnalysisRunCreate(BaseModel):
    query: str
    llm_provider: str


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    conversation_id: UUID
    query: str
    llm_provider: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AnalysisRunListResponse(BaseModel):
    items: list[AnalysisRunResponse]
    total: int


class ConversationQueryResponse(BaseModel):
    message: MessageResponse
    analysis_run: AnalysisRunResponse


class AnalysisExecutionResponse(BaseModel):
    analysis_run: AnalysisRunResponse
    message: MessageResponse
