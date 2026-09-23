from app.core.tracing import traced, trace_event

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import AnalysisRunStatus, MAX_CONVERSATION_CONTEXT_MESSAGES
from app.core.exceptions import (
    AgentExecutionError,
    AnalysisPlanInvalidError,
    AnalysisPlanPersistenceError,
    AnalysisRunNotExecutableError,
    AnalysisRunNotFoundError,
    DatasetNotProfiledError,
    InsufficientCreditsError,
    LLMRequestError,
    AnalysisToolError,
)
from app.graph.state import AnalysisState
from app.graph.workflow import AnalysisWorkflow
from app.models.agent_run import AgentRun
from app.models.analysis_plan import AnalysisPlan
from app.models.evidence import Evidence
from app.models.statistical_validation import StatisticalValidation
from app.models.analysis_run import AnalysisRun
from app.models.dataset import Dataset
from app.models.dataset_profile import DatasetProfile, DatasetProfileStatus
from app.models.message import Message
from app.models.report import Report
from app.services.analysis_recovery import recovery_report
from app.models.user import User
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.dataset_profile_repository import DatasetProfileRepository
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.llm import LLMResult
from app.services.agent_run_service import AgentRunService
from app.services.analysis_plan_service import AgentSemanticValidationError, AnalysisPlanService
from app.services.llm.base import LLMProviderError
from app.services.llm.llm_service import LLMService
from app.services.message_service import MessageService
from app.services.profile_context_service import ProfileContextService
from app.services.analysis_task_execution_service import AnalysisTaskExecutionService, TaskExecutionFailure
from app.services.dataset_file_service import DatasetFileDownloadError
from app.services.dataset_loader_service import DatasetParseError, DatasetRowLimitError, UnsupportedDatasetStructureError
from app.services.evidence_service import EvidencePersistenceError
from app.services.statistical_validation_service import StatisticalValidationPersistenceError
from app.services.stage9_service import Stage9Failure, Stage9Service
from app.tools.analytics import ToolValidationError
from app.tools.statistics import StatisticalToolError
from app.agents.analyst import NumericGroundingError

logger = logging.getLogger(__name__)

AGENT_FAILURE_CODES = {
    "supervisor": "AGENT_SUPERVISOR_FAILED",
    "profile_interpreter": "AGENT_PROFILE_INTERPRETER_FAILED",
    "planner": "AGENT_PLANNER_FAILED",
}


class StageAgentFailure(Exception):
    def __init__(self, code: str, safe_message: str, internal_detail: str | None = None) -> None:
        self.code = code
        self.safe_message = safe_message
        self.internal_detail = internal_detail
        super().__init__(safe_message)


class AnalysisExecutionService:
    def __init__(
        self,
        session: AsyncSession,
        llm_service: LLMService | None = None,
        workflow: AnalysisWorkflow | None = None,
    ) -> None:
        self.session = session
        self.runs = AnalysisRunRepository(session)
        self.agent_runs = AgentRunRepository(session)
        self.agent_run_service = AgentRunService(session)
        self.datasets = DatasetRepository(session)
        self.profiles = DatasetProfileRepository(session)
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.users = UserRepository(session)
        self.message_service = MessageService(session)
        self.plan_service = AnalysisPlanService(session)
        self.profile_context_service = ProfileContextService()
        self.llm_service = llm_service or LLMService()
        self.task_execution = AnalysisTaskExecutionService(session, self.llm_service)
        self.stage9 = Stage9Service(session, self.llm_service)
        self.workflow = workflow

    @traced("analysis.request")
    async def execute(self, analysis_run_id: UUID, user: User) -> tuple[AnalysisRun, Message]:
        run = await self.runs.get_by_id_for_user(analysis_run_id, user.id)
        if run is None:
            raise AnalysisRunNotFoundError
        if run.status != AnalysisRunStatus.PENDING.value:
            raise AnalysisRunNotExecutableError

        dataset, profile, conversation_context = await self._load_context(run, user)
        try:
            model_name = self.llm_service.model_name(run.llm_provider)
        except LLMProviderError as exc:
            logger.warning("Provider unavailable; recovery remains available code=%s", exc.code)
            model_name = "unavailable"

        profile_context = self.profile_context_service.build(
            profile, file_name=dataset.original_file_name
        )
        started_at = datetime.now(timezone.utc)
        try:
            claimed = await self.runs.claim_pending(
                analysis_run_id=run.id, user_id=user.id, started_at=started_at
            )
            if claimed is None:
                await self.session.rollback()
                raise AnalysisRunNotExecutableError
            run = claimed
            await self.session.commit()
        except AnalysisRunNotExecutableError:
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Analysis execution setup failed analysis_run_id=%s provider=%s", run.id, run.llm_provider)
            raise LLMRequestError("LLM_EXECUTION_FAILED", "The analysis execution could not be started.") from exc

        run_id = run.id
        run_provider = run.llm_provider

        async def run_agent(
            agent_name: str,
            input_json: dict[str, Any],
            invoke: Callable[[], Awaitable[LLMResult]],
        ) -> LLMResult:
            return await self._run_agent(run, agent_name, model_name, input_json, invoke)

        async def analysis_executor(state: AnalysisState) -> dict[str, object]:
            plan_output = AnalysisPlanOutput.model_validate(state["analysis_plan"])
            evidence = await self.task_execution.execute_analysis(run=run, dataset=dataset, plan_output=plan_output, profile=profile_context, run_agent=run_agent)
            return {"evidence": evidence}

        async def statistics_executor(state: AnalysisState) -> dict[str, object]:
            plan_output = AnalysisPlanOutput.model_validate(state["analysis_plan"])
            try:
                validations = await self.task_execution.execute_statistics(run=run, plan_output=plan_output, profile=profile_context, run_agent=run_agent)
            except (StageAgentFailure, StatisticalToolError) as exc:
                await trace_event("statistics_unavailable", outcome="partial")
                logger.warning("Continuing without statistical conclusions analysis_run_id=%s error_type=%s", run_id, type(exc).__name__)
                self.task_execution.warnings.append("Statistical checks could not be completed. The results describe observed patterns only and do not establish a cause.")
                validations = []
            return {"statistical_validations": validations}

        async def claim_executor(state: AnalysisState) -> dict[str, object]:
            claims = await self.stage9.generate_fallback_claims(run=run, evidence=state.get("evidence") or [])
            return {"claims": claims}

        async def critic_executor(state: AnalysisState) -> dict[str, object]:
            try:
                reviews, accepted = await self.stage9.review_claims(
                    run=run,
                    claims=state.get("claims") or [],
                    evidence=state.get("evidence") or [],
                    validations=state.get("statistical_validations") or [],
                    quality_warnings=profile_context.get("quality_issues") or [],
                    run_agent=run_agent,
                )
            except (StageAgentFailure, Stage9Failure) as exc:
                await trace_event("critic_fallback", outcome="completed_with_fallback")
                logger.warning("Using deterministic claim-review fallback analysis_run_id=%s reason=%s", run.id, getattr(exc, "internal_detail", None) or exc)
                reviews, accepted = await self.stage9.accept_fallback_claims(run=run, claims=state.get("claims") or [])
            return {"claim_reviews": reviews, "accepted_claims": accepted}

        async def visualization_executor(state: AnalysisState) -> dict[str, object]:
            try:
                charts = await self.stage9.create_charts(
                    run=run,
                    claims=state.get("accepted_claims") or [],
                    evidence=state.get("evidence") or [],
                    columns=profile_context.get("columns") or [],
                    run_agent=run_agent,
                )
            except (StageAgentFailure, Stage9Failure) as exc:
                detail = getattr(exc, "internal_detail", None) or getattr(exc, "detail", None) or str(exc)
                logger.warning(
                    "Visualization skipped analysis_run_id=%s error_code=%s reason=%s",
                    run.id,
                    getattr(exc, "code", "VISUALIZATION_FAILED"),
                    detail,
                    extra={
                        "analysis_run_id": str(run.id),
                        "error_code": getattr(exc, "code", "VISUALIZATION_FAILED"),
                        "validation_reason": detail,
                    },
                )
                charts = await self.stage9.create_fallback_charts(
                    run=run,
                    claims=state.get("accepted_claims") or [],
                    evidence=state.get("evidence") or [],
                    columns=profile_context.get("columns") or [],
                )
                await trace_event("visualization_fallback", outcome="completed_with_fallback")
            return {"chart_specs": charts}

        async def report_executor(state: AnalysisState) -> dict[str, object]:
            report = await self._generate_report(
                run=run,
                state=state,
                quality_warnings=[*(profile_context.get("quality_issues") or []), *[{"message": note} for note in self.task_execution.warnings]],
                run_agent=run_agent,
            )
            return {"final_report": report}

        workflow = self.workflow or AnalysisWorkflow(
            self.llm_service,
            run_agent,
            analysis_executor,
            statistics_executor,
            claim_executor,
            critic_executor,
            visualization_executor,
            report_executor,
        )
        state = self._initial_state(run, profile_context, conversation_context)
        try:
            try:
                result = await workflow.execute(state)
            except Exception as exc:
                await trace_event("workflow_recovery", outcome="recovered_partial")
                logger.exception("Recovering interrupted analysis analysis_run_id=%s provider=%s error_type=%s", run_id, run_provider, type(exc).__name__)
                return await self._recover_response(run_id, profile_context)
            return await self._complete(run, result)
        except StageAgentFailure as exc:
            logger.error(
                "Analysis stage failed analysis_run_id=%s provider=%s error_code=%s reason=%s",
                run_id,
                run_provider,
                exc.code,
                exc.internal_detail or exc.safe_message,
                extra={
                    "analysis_run_id": str(run_id),
                    "provider": run_provider,
                    "error_code": exc.code,
                    "validation_reason": exc.internal_detail,
                },
            )
            await self._fail_run(run_id, exc.code, exc.safe_message)
            if exc.code == "ANALYSIS_PLAN_INVALID":
                raise AnalysisPlanInvalidError(exc.safe_message) from exc
            if exc.code in AGENT_FAILURE_CODES.values():
                raise AgentExecutionError(exc.code) from exc
            if exc.code in AnalysisToolError._MESSAGES:
                raise AnalysisToolError(exc.code) from exc
            raise LLMRequestError(exc.code, exc.safe_message) from exc
        except AgentSemanticValidationError as exc:
            await self._fail_run(run_id, exc.code, exc.safe_message)
            raise AnalysisPlanInvalidError(exc.safe_message) from exc
        except AnalysisPlanPersistenceError as exc:
            await self._fail_run(run_id, exc.code, exc.message)
            raise
        except Stage9Failure as exc:
            message = AnalysisToolError._MESSAGES[exc.code]
            await self._fail_run(run_id, exc.code, message)
            raise AnalysisToolError(exc.code) from exc
        except (TaskExecutionFailure, ToolValidationError, DatasetFileDownloadError, DatasetParseError, DatasetRowLimitError, UnsupportedDatasetStructureError, StatisticalToolError, EvidencePersistenceError, StatisticalValidationPersistenceError) as exc:
            code = getattr(exc, "code", "ANALYSIS_TOOL_EXECUTION_FAILED")
            if isinstance(exc, ToolValidationError): code = "ANALYSIS_TOOL_VALIDATION_FAILED"
            if isinstance(exc, StatisticalToolError): code = "STATISTICAL_TEST_FAILED"
            logger.error(
                "Analysis operation failed analysis_run_id=%s provider=%s error_code=%s reason=%s",
                run_id,
                run_provider,
                code,
                getattr(exc, "detail", None) or str(exc),
                extra={
                    "analysis_run_id": str(run_id),
                    "provider": run_provider,
                    "error_code": code,
                    "validation_reason": getattr(exc, "detail", None) or str(exc),
                },
            )
            await self._fail_run(run_id, code, AnalysisToolError._MESSAGES[code])
            raise AnalysisToolError(code) from exc
        except Exception as exc:
            safe_message = "The analysis execution could not be completed."
            await self._fail_run(run_id, "LLM_EXECUTION_FAILED", safe_message)
            logger.exception("Analysis execution failed analysis_run_id=%s provider=%s error_type=%s", run_id, run_provider, type(exc).__name__)
            raise LLMRequestError("LLM_EXECUTION_FAILED", safe_message) from exc

    async def _generate_report(
        self,
        *,
        run: AnalysisRun,
        state: AnalysisState,
        quality_warnings: list[dict[str, Any]],
        run_agent: Callable[..., Awaitable[LLMResult]],
    ) -> dict[str, Any]:
        inputs = {
            "run": run,
            "claims": state.get("accepted_claims") or [],
            "evidence": state.get("evidence") or [],
            "validations": state.get("statistical_validations") or [],
            "quality_warnings": quality_warnings,
        }
        if inputs["claims"]:
            try:
                return await self.stage9.create_report(
                    **inputs,
                    charts=state.get("chart_specs") or [],
                    run_agent=run_agent,
                )
            except (StageAgentFailure, Stage9Failure) as exc:
                # Persistence failures belong to global recovery; do not retry a write.
                if isinstance(exc, Stage9Failure) and exc.code != "REPORT_VALIDATION_FAILED":
                    raise
                logger.warning(
                    "Using evidence-based report fallback analysis_run_id=%s provider=%s error_code=%s",
                    run.id, run.llm_provider, exc.code,
                    extra={"analysis_run_id": str(run.id), "provider": run.llm_provider, "error_code": exc.code},
                )
                await trace_event("report_fallback", error_code=exc.code, outcome="completed_with_fallback")
        else:
            # No reviewed findings means there is no grounded input for the report agent.
            await trace_event("report_without_accepted_claims", outcome="partial")
        return await self.stage9.create_fallback_report(**inputs)

    async def list_agent_runs(self, analysis_run_id: UUID, user: User) -> list[AgentRun]:
        run = await self.runs.get_by_id_for_user(analysis_run_id, user.id)
        if run is None:
            raise AnalysisRunNotFoundError
        return await self.agent_run_service.list_for_run(run.id)

    @traced("fallback.recover_response")
    async def _recover_response(self, run_id: UUID, profile_context: dict) -> tuple[AnalysisRun, Message]:
        # Roll back only unfinished work. Read committed results rather than stale ORM state.
        await self.session.rollback()
        run = await self.session.get(AnalysisRun, run_id)
        if run is None:
            raise AnalysisRunNotFoundError
        saved = await self.stage9.reports.get_for_run(run_id)
        findings = []
        notes = list(getattr(getattr(self, "task_execution", None), "warnings", []))
        for claim in await self.stage9.claims.list_for_run(run_id):
            if claim.status != "accepted" or claim.claim_type != "descriptive":
                continue
            refs = [item.evidence_code for item in claim.evidence_items]
            if not refs:
                continue
            wording = claim.review.corrected_wording if claim.review else None
            findings.append({"claim_code": claim.claim_code, "finding": wording or claim.claim_text, "evidence_codes": refs})
            notes.extend(note for item in claim.evidence_items for note in (item.limitations or []))
        payload = recovery_report(profile_context, findings, notes)
        if not findings and saved is None:
            # Only display raw calculated values, never an unreviewed model interpretation.
            evidence = await self.stage9.evidence_repo.list_for_run(run_id)
            from types import SimpleNamespace
            from app.agents.analyst import AnalystAgent
            for item in evidence:
                if item.method not in {"groupby_aggregate", "time_series_aggregate", "distribution_summary"}:
                    continue
                summary = AnalystAgent._fallback_interpretation({}, SimpleNamespace(result=item.result, tool=item.method))
                payload["data_notes"].append(summary.interpretation)
            if evidence:
                payload["executive_summary"] = 'I could not finish the full answer. Any completed calculations that can be summarized safely are listed under Data notes; these have not received the full review.'
        if saved is not None:
            # A persisted report already contains validated findings; preserve its content.
            payload = dict(saved.report)
            payload["limitations"] = list(dict.fromkeys([*(payload.get("limitations") or []), "Some final steps could not be completed; the saved results are shown."]))
            saved.limitations = payload["limitations"]
            saved.report = payload
        else:
            saved = Report(analysis_run_id=run_id, report=payload, **payload)
            await self.stage9.reports.create(saved)
        # Do not persist an incomplete plan again during response completion.
        return await self._complete(run, {"assistant_message": self.stage9.format_report(payload)})

    async def get_plan(self, analysis_run_id: UUID, user: User) -> AnalysisPlan:
        return await self.plan_service.get_for_run(analysis_run_id, user.id)

    async def list_evidence(self, analysis_run_id: UUID, user: User) -> list[Evidence]:
        return await self.task_execution.evidence_service.list_owned(analysis_run_id, user.id)

    async def list_statistical_validations(self, analysis_run_id: UUID, user: User) -> list[StatisticalValidation]:
        return await self.task_execution.stat_service.list_owned(analysis_run_id, user.id)

    async def list_claims(self, analysis_run_id: UUID, user: User):
        return await self.stage9.list_claims_owned(analysis_run_id, user.id)

    async def list_charts(self, analysis_run_id: UUID, user: User):
        return await self.stage9.list_charts_owned(analysis_run_id, user.id)

    async def get_report(self, analysis_run_id: UUID, user: User):
        return await self.stage9.get_report_owned(analysis_run_id, user.id)

    @traced("agent")
    async def _run_agent(
        self,
        run: AnalysisRun,
        agent_name: str,
        model_name: str,
        input_json: dict[str, Any],
        invoke: Callable[[], Awaitable[LLMResult]],
    ) -> LLMResult:
        run_id = run.id
        run_provider = run.llm_provider
        started_at = datetime.now(timezone.utc)
        try:
            agent_run = await self.agent_run_service.start(
                analysis_run_id=run_id,
                agent_name=agent_name,
                provider=run_provider,
                model=model_name,
                input_json=input_json,
                started_at=started_at,
            )
            await self.session.commit()
            agent_run_id = agent_run.id
        except Exception as exc:
            await self.session.rollback()
            raise StageAgentFailure(
                self._agent_failure_code(agent_name),
                "The analysis agent could not be started.",
            ) from exc

        try:
            result = await invoke()
            completed_at = datetime.now(timezone.utc)
            usage = result.usage
            await self.agent_runs.mark_completed(
                agent_run,
                output_json=result.content,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=result.latency_ms,
                completed_at=completed_at,
            )
            await self.session.commit()
            logger.info(
                "Agent completed analysis_run_id=%s agent_run_id=%s agent_name=%s provider=%s model=%s status=completed latency_ms=%s",
                run_id, agent_run_id, agent_name, run_provider, model_name, result.latency_ms,
            )
            return result
        except Exception as exc:
            await self.session.rollback()
            code, message = self._safe_agent_error(agent_name, exc)
            persisted = await self.agent_runs.get_by_id(agent_run_id)
            if persisted is not None:
                await self.agent_runs.mark_failed(
                    persisted,
                    error_code=code,
                    error_message=message,
                    completed_at=datetime.now(timezone.utc),
                )
                await self.session.commit()
            await self.session.refresh(run)
            logger.warning(
                "Agent failed analysis_run_id=%s agent_run_id=%s agent_name=%s provider=%s model=%s status=failed error_code=%s reason=%s",
                run_id, agent_run_id, agent_name, run_provider, model_name, code, self._internal_error_detail(exc),
                extra={
                    "analysis_run_id": str(run_id),
                    "agent_run_id": str(agent_run_id),
                    "agent_name": agent_name,
                    "provider": run_provider,
                    "model": model_name,
                    "error_code": code,
                    "error_type": type(exc).__name__,
                    "validation_reason": self._internal_error_detail(exc),
                },
            )
            raise StageAgentFailure(code, message, self._internal_error_detail(exc)) from exc

    @staticmethod
    def _internal_error_detail(exc: Exception) -> str:
        detail = getattr(exc, "detail", None) or str(exc)
        cause = exc.__cause__
        if cause is not None and str(cause) and str(cause) not in detail:
            detail = f"{detail} Caused by: {cause}"
        return detail

    @staticmethod
    def _safe_agent_error(agent_name: str, exc: Exception) -> tuple[str, str]:
        if isinstance(exc, LLMProviderError):
            return exc.code, exc.safe_message
        if isinstance(exc, AgentSemanticValidationError):
            return exc.code, exc.safe_message
        if isinstance(exc, Stage9Failure):
            return exc.code, AnalysisToolError._MESSAGES[exc.code]
        if isinstance(exc, (ToolValidationError, NumericGroundingError)):
            return "ANALYSIS_TOOL_VALIDATION_FAILED", AnalysisToolError._MESSAGES["ANALYSIS_TOOL_VALIDATION_FAILED"]
        if isinstance(exc, StatisticalToolError):
            return "STATISTICAL_TEST_FAILED", AnalysisToolError._MESSAGES["STATISTICAL_TEST_FAILED"]
        return AnalysisExecutionService._agent_failure_code(agent_name), "The analysis agent returned an invalid response."

    @staticmethod
    def _agent_failure_code(agent_name: str) -> str:
        if agent_name.startswith("analyst:"):
            return "ANALYSIS_TOOL_EXECUTION_FAILED"
        if agent_name.startswith("statistical_validator:"):
            return "STATISTICAL_VALIDATION_FAILED"
        if agent_name == "claim_generator":
            return "CLAIM_GENERATION_FAILED"
        if agent_name.startswith("critic:"):
            return "CRITIC_EXECUTION_FAILED"
        if agent_name == "visualization":
            return "VISUALIZATION_FAILED"
        if agent_name == "report":
            return "REPORT_GENERATION_FAILED"
        return AGENT_FAILURE_CODES[agent_name]

    async def _load_context(self, run: AnalysisRun, user: User) -> tuple[Dataset, DatasetProfile, list[Message]]:
        dataset = await self.datasets.get_for_user(dataset_id=run.dataset_id, user_id=user.id)
        conversation = await self.conversations.get_by_id_for_user(run.conversation_id, user.id)
        if dataset is None or conversation is None or conversation.dataset_id != dataset.id:
            raise AnalysisRunNotFoundError
        profile = await self.profiles.get_by_dataset_id(dataset.id)
        if profile is None or profile.profile_status != DatasetProfileStatus.COMPLETED.value:
            raise DatasetNotProfiledError
        messages = await self.messages.list_recent_for_conversation(
            conversation.id, limit=MAX_CONVERSATION_CONTEXT_MESSAGES
        )
        return dataset, profile, messages

    async def _complete(self, run: AnalysisRun, result: AnalysisState) -> tuple[AnalysisRun, Message]:
        assistant_content = result.get("assistant_message")
        if not assistant_content:
            raise ValueError("The graph did not prepare an assistant message.")
        try:
            if result.get("analysis_plan") is not None and self.task_execution.plan is None:
                plan_output = AnalysisPlanOutput.model_validate(result["analysis_plan"])
                available_columns = {
                    column["name"]
                    for column in (result.get("dataset_profile") or {}).get("columns", [])
                }
                await self.plan_service.persist_validated(
                    run.id, plan_output, available_columns
                )
            message = await self.message_service.create_assistant_message(
                run.conversation_id, run, assistant_content
            )
            remaining_credits = await self.users.consume_credit(run.user_id)
            if remaining_credits is None:
                raise InsufficientCreditsError
            completed_at = datetime.now(timezone.utc)
            await self.runs.update_status(
                run,
                AnalysisRunStatus.COMPLETED.value,
                started_at=run.started_at,
                completed_at=completed_at,
                error_code=None,
                error_message=None,
            )
            await self.session.commit()
            await self.session.refresh(run)
            await self.session.refresh(message)
            return run, message
        except Exception:
            await self.session.rollback()
            raise

    async def _fail_run(self, analysis_run_id: UUID, error_code: str, error_message: str) -> None:
        try:
            await self.session.rollback()
            run = await self.session.get(AnalysisRun, analysis_run_id)
            if run is None:
                raise RuntimeError("Analysis run is missing.")
            await self.runs.update_status(
                run,
                AnalysisRunStatus.FAILED.value,
                started_at=run.started_at,
                completed_at=datetime.now(timezone.utc),
                error_code=error_code,
                error_message=error_message,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("Analysis failure persistence failed analysis_run_id=%s", analysis_run_id)

    @staticmethod
    def _initial_state(run: AnalysisRun, profile_context: dict[str, Any], conversation_context: list[Message]) -> AnalysisState:
        return {
            "analysis_run_id": str(run.id),
            "user_id": str(run.user_id),
            "dataset_id": str(run.dataset_id),
            "conversation_id": str(run.conversation_id),
            "user_query": run.query,
            "llm_provider": run.llm_provider,
            "dataset_profile": profile_context,
            "conversation_context": [{"role": message.role, "content": message.content} for message in conversation_context],
            "supervisor_decision": None,
            "profile_interpretation": None,
            "analysis_plan": None,
            "evidence": None,
            "statistical_validations": None,
            "claims": None,
            "claim_reviews": None,
            "accepted_claims": None,
            "chart_specs": None,
            "final_report": None,
            "current_node": None,
            "assistant_message": None,
            "error_code": None,
            "error_message": None,
        }
