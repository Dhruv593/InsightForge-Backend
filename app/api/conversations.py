from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    CurrentUser,
    get_analysis_run_service,
    get_conversation_service,
    get_message_service,
)
from app.schemas.analysis_run import (
    AnalysisRunCreate,
    AnalysisRunListResponse,
    AnalysisRunResponse,
    ConversationQueryResponse,
)
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDeleteResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
)
from app.schemas.message import MessageListResponse, MessageResponse
from app.services.analysis_run_service import AnalysisRunService
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    user: CurrentUser,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.create_conversation(payload.dataset_id, payload.title, user)
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user: CurrentUser,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    dataset_id: Annotated[UUID | None, Query()] = None,
) -> ConversationListResponse:
    conversations = await service.list_conversations(user, dataset_id)
    items = [ConversationResponse.model_validate(item) for item in conversations]
    return ConversationListResponse(items=items, total=len(items))


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    user: CurrentUser,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.get_conversation(conversation_id, user)
    return ConversationResponse.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    user: CurrentUser,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.update_conversation(conversation_id, payload.title, user)
    return ConversationResponse.model_validate(conversation)


@router.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
async def delete_conversation(
    conversation_id: UUID,
    user: CurrentUser,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationDeleteResponse:
    await service.delete_conversation(conversation_id, user)
    return ConversationDeleteResponse()


@router.post(
    "/{conversation_id}/query",
    response_model=ConversationQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_query(
    conversation_id: UUID,
    payload: AnalysisRunCreate,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> ConversationQueryResponse:
    message, analysis_run = await service.create_pending_run(
        conversation_id, payload.query, payload.llm_provider, user
    )
    return ConversationQueryResponse(
        message=MessageResponse.model_validate(message),
        analysis_run=AnalysisRunResponse.model_validate(analysis_run),
    )


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    user: CurrentUser,
    service: Annotated[MessageService, Depends(get_message_service)],
) -> MessageListResponse:
    messages = await service.list_messages(conversation_id, user)
    items = [MessageResponse.model_validate(item) for item in messages]
    return MessageListResponse(items=items, total=len(items))


@router.get("/{conversation_id}/analysis-runs", response_model=AnalysisRunListResponse)
async def list_analysis_runs(
    conversation_id: UUID,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> AnalysisRunListResponse:
    runs = await service.list_runs(conversation_id, user)
    items = [AnalysisRunResponse.model_validate(item) for item in runs]
    return AnalysisRunListResponse(items=items, total=len(items))
