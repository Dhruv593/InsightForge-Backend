from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.api.dependencies import (
    CurrentUser,
    get_analysis_execution_service,
    get_analysis_run_service,
)
from app.schemas.agent_run import AgentRunListResponse, AgentRunResponse
from app.schemas.analysis_plan import AnalysisPlanResponse
from app.schemas.analysis_run import ActiveAnalysisQueueResponse, AnalysisQueueResponse, AnalysisRunResponse, AnalysisRunRetry, ConversationQueryResponse
from app.schemas.message import MessageResponse
from app.schemas.evidence import EvidenceListResponse, EvidenceResponse
from app.schemas.statistical_validation import StatisticalValidationListResponse, StatisticalValidationResponse
from app.schemas.claim import ClaimListResponse, ClaimResponse
from app.schemas.chart import ChartListResponse, ChartResponse
from app.schemas.report import ReportResponse
from app.services.analysis_execution_service import AnalysisExecutionService
from app.services.analysis_run_service import AnalysisRunService

router = APIRouter(prefix="/analysis-runs", tags=["analysis-runs"])


@router.get("/queue/active", response_model=ActiveAnalysisQueueResponse)
async def list_active_queue(user: CurrentUser, service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)]) -> ActiveAnalysisQueueResponse:
    items = await service.list_active_runs(user)
    return ActiveAnalysisQueueResponse(items=[AnalysisRunResponse.model_validate(item) for item in items], total=len(items))


@router.post("/{analysis_run_id}/execute", response_model=AnalysisQueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_analysis_run(
    analysis_run_id: UUID,
    request: Request,
    user: CurrentUser,
    service: Annotated[
        AnalysisRunService,
        Depends(get_analysis_run_service),
    ],
) -> AnalysisQueueResponse:
    analysis_run, queue_position = await service.queue_position(analysis_run_id, user)
    queue = getattr(request.app.state, "analysis_queue", None)
    if queue:
        queue.notify()
    return AnalysisQueueResponse(analysis_run=AnalysisRunResponse.model_validate(analysis_run), queue_position=queue_position)


@router.post("/{analysis_run_id}/retry", response_model=ConversationQueryResponse, status_code=status.HTTP_201_CREATED)
async def retry_analysis_run(
    analysis_run_id: UUID,
    payload: AnalysisRunRetry,
    request: Request,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> ConversationQueryResponse:
    message, analysis_run = await service.retry_run(analysis_run_id, user, payload.llm_provider)
    queue = getattr(request.app.state, "analysis_queue", None)
    if queue:
        queue.notify()
    return ConversationQueryResponse(message=MessageResponse.model_validate(message), analysis_run=AnalysisRunResponse.model_validate(analysis_run))


@router.post("/{analysis_run_id}/cancel", response_model=AnalysisRunResponse)
async def cancel_analysis_run(
    analysis_run_id: UUID,
    request: Request,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> AnalysisRunResponse:
    analysis_run = await service.cancel_run(analysis_run_id, user)
    queue = getattr(request.app.state, "analysis_queue", None)
    if queue:
        queue.cancel(analysis_run_id)
    return AnalysisRunResponse.model_validate(analysis_run)


@router.get("/{analysis_run_id}/queue", response_model=AnalysisQueueResponse)
async def get_queue_status(
    analysis_run_id: UUID,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> AnalysisQueueResponse:
    analysis_run, queue_position = await service.queue_position(analysis_run_id, user)
    return AnalysisQueueResponse(analysis_run=AnalysisRunResponse.model_validate(analysis_run), queue_position=queue_position)


@router.get("/{analysis_run_id}/agent-runs", response_model=AgentRunListResponse)
async def list_agent_runs(
    analysis_run_id: UUID,
    user: CurrentUser,
    service: Annotated[
        AnalysisExecutionService,
        Depends(get_analysis_execution_service),
    ],
) -> AgentRunListResponse:
    items = await service.list_agent_runs(analysis_run_id, user)
    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.get("/{analysis_run_id}/plan", response_model=AnalysisPlanResponse)
async def get_analysis_plan(
    analysis_run_id: UUID,
    user: CurrentUser,
    service: Annotated[
        AnalysisExecutionService,
        Depends(get_analysis_execution_service),
    ],
) -> AnalysisPlanResponse:
    plan = await service.get_plan(analysis_run_id, user)
    return AnalysisPlanResponse.model_validate(plan)


@router.get("/{analysis_run_id}/evidence", response_model=EvidenceListResponse)
async def list_evidence(analysis_run_id: UUID, user: CurrentUser, service: Annotated[AnalysisExecutionService, Depends(get_analysis_execution_service)]) -> EvidenceListResponse:
    items = await service.list_evidence(analysis_run_id, user)
    return EvidenceListResponse(items=[EvidenceResponse.model_validate(item) for item in items], total=len(items))


@router.get("/{analysis_run_id}/statistical-validations", response_model=StatisticalValidationListResponse)
async def list_statistical_validations(analysis_run_id: UUID, user: CurrentUser, service: Annotated[AnalysisExecutionService, Depends(get_analysis_execution_service)]) -> StatisticalValidationListResponse:
    items = await service.list_statistical_validations(analysis_run_id, user)
    return StatisticalValidationListResponse(items=[StatisticalValidationResponse.model_validate(item) for item in items], total=len(items))


@router.get("/{analysis_run_id}/claims", response_model=ClaimListResponse)
async def list_claims(analysis_run_id: UUID, user: CurrentUser, service: Annotated[AnalysisExecutionService, Depends(get_analysis_execution_service)]) -> ClaimListResponse:
    items = await service.list_claims(analysis_run_id, user)
    responses = [
        ClaimResponse.model_validate({
            "id": item.id,
            "analysis_run_id": item.analysis_run_id,
            "claim_code": item.claim_code,
            "claim_text": item.claim_text,
            "claim_type": item.claim_type,
            "status": item.status,
            "evidence_codes": [evidence.evidence_code for evidence in item.evidence_items],
            "review": None if item.review is None else {
                "status": item.review.status,
                "evidence_strength": item.review.evidence_strength,
                "issues": item.review.issues,
                "missing_analysis": item.review.missing_analysis,
                "corrected_wording": item.review.corrected_wording,
            },
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }) for item in items
    ]
    return ClaimListResponse(items=responses, total=len(responses))


@router.get("/{analysis_run_id}/charts", response_model=ChartListResponse)
async def list_charts(analysis_run_id: UUID, user: CurrentUser, service: Annotated[AnalysisExecutionService, Depends(get_analysis_execution_service)]) -> ChartListResponse:
    items = await service.list_charts(analysis_run_id, user)
    return ChartListResponse(items=[ChartResponse.model_validate(item) for item in items], total=len(items))


@router.get("/{analysis_run_id}/report", response_model=ReportResponse)
async def get_report(analysis_run_id: UUID, user: CurrentUser, service: Annotated[AnalysisExecutionService, Depends(get_analysis_execution_service)]) -> ReportResponse:
    return ReportResponse.model_validate(await service.get_report(analysis_run_id, user))


@router.get("/{analysis_run_id}", response_model=AnalysisRunResponse)
async def get_analysis_run(
    analysis_run_id: UUID,
    user: CurrentUser,
    service: Annotated[AnalysisRunService, Depends(get_analysis_run_service)],
) -> AnalysisRunResponse:
    analysis_run = await service.get_run(analysis_run_id, user)
    return AnalysisRunResponse.model_validate(analysis_run)
