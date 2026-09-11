from app.core.tracing import traced

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents import AnalystAgent, StatisticalValidatorAgent
from app.core.analysis_constants import AnalysisTaskStatus
from app.core.config import get_settings
from app.models.analysis_run import AnalysisRun
from app.models.analysis_task import AnalysisTask
from app.models.dataset import Dataset
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.llm import LLMResult
from app.services.analysis_plan_service import AnalysisPlanService
from app.services.dataset_file_service import DatasetFileService
from app.services.dataset_loader_service import DatasetLoaderService
from app.services.evidence_service import EvidencePersistenceError, EvidenceService
from app.services.statistical_validation_service import StatisticalValidationPersistenceError, StatisticalValidationService

AgentRunner = Callable[[str, dict[str, Any], Callable[[], Awaitable[LLMResult]]], Awaitable[LLMResult]]
logger = logging.getLogger(__name__)


class TaskExecutionFailure(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class AnalysisTaskExecutionService:
    def __init__(self, session, llm_service) -> None:
        self.session = session
        self.plan_service = AnalysisPlanService(session)
        self.evidence_service = EvidenceService(session)
        self.stat_service = StatisticalValidationService(session)
        self.analyst = AnalystAgent(llm_service)
        self.validator = StatisticalValidatorAgent(llm_service)
        self.files = DatasetFileService()
        self.loader = DatasetLoaderService(get_settings().max_profile_rows)
        self.dataframe = None
        self.plan = None
        self.task_specs: list[dict[str, Any]] = []
        self.evidence_by_task: dict[str, Any] = {}
        self.warnings: list[str] = []

    @traced("tools.analysis")
    async def execute_analysis(self, *, run: AnalysisRun, dataset: Dataset, plan_output: AnalysisPlanOutput, profile: dict[str, Any], run_agent: AgentRunner) -> list[dict[str, Any]]:
        self.warnings.extend(plan_output.limitations)
        columns = {column["name"] for column in profile["columns"]}
        await self.plan_service.persist_validated(run.id, plan_output, columns)
        await self.session.commit()
        self.plan = await self.plan_service.plans.get_by_analysis_run_id(run.id)
        file_bytes = await self.files.download(dataset)
        loaded = await asyncio.to_thread(self.loader.load, file_bytes, dataset.file_type)
        self.dataframe = loaded.dataframe.copy(deep=True)
        ordered = self._topological_tasks(self.plan.tasks)
        self.task_specs = [{"id": task.id, **self._task_payload(task)} for task in ordered]
        failed: set[str] = set()
        failure_codes: set[str] = set()
        failure_details: list[str] = []
        evidence_output: list[dict[str, Any]] = []
        for task in self.task_specs:
            task_code = task["task_code"]
            persisted = await self.session.get(AnalysisTask, task["id"])
            if persisted is None:
                raise TaskExecutionFailure("ANALYSIS_TOOL_EXECUTION_FAILED")
            if any(dependency in failed for dependency in task["depends_on"]):
                await self.plan_service.tasks.update_status(persisted, AnalysisTaskStatus.SKIPPED.value, reason="Skipped because a required dependency did not complete.")
                await self.session.commit(); failed.add(task_code); continue
            if task["analysis_type"] == "regression":
                await self.plan_service.tasks.update_status(persisted, AnalysisTaskStatus.FAILED.value, reason="The planned analytical method is not supported yet.")
                await self.session.commit()
                failed.add(task_code)
                failure_codes.add("ANALYSIS_METHOD_NOT_SUPPORTED")
                continue
            await self.plan_service.tasks.update_status(persisted, AnalysisTaskStatus.RUNNING.value)
            await self.session.commit()
            task_payload = {key: value for key, value in task.items() if key != "id"}
            dependencies = [self.evidence_by_task[code].result for code in task["depends_on"] if code in self.evidence_by_task]

            async def invoke(task_payload=task_payload, dependencies=dependencies):
                return await self.analyst.run(provider=run.llm_provider, query=run.query, task=task_payload, verified_columns=sorted(columns), profile_metadata=profile, dataframe=self.dataframe, prior_evidence=dependencies)
            try:
                result = await run_agent(f"analyst:{task_code}", {"task": task_payload, "dependency_evidence_codes": task["depends_on"]}, invoke)
                evidence = await self.evidence_service.create(run_id=run.id, task_id=task["id"], code=f"{task_code}_E1", content=result.content)
                persisted = await self.session.get(AnalysisTask, task["id"])
                if persisted is None:
                    raise TaskExecutionFailure("ANALYSIS_TOOL_EXECUTION_FAILED")
                await self.plan_service.tasks.update_status(persisted, AnalysisTaskStatus.COMPLETED.value)
                await self.session.commit()
                self.evidence_by_task[task_code] = evidence
                evidence_output.append(self._evidence_dict(evidence))
            except Exception as exc:
                await self.session.rollback()
                persisted = await self.session.get(AnalysisTask, task["id"])
                if persisted is None:
                    raise TaskExecutionFailure("ANALYSIS_TOOL_EXECUTION_FAILED") from exc
                await self.plan_service.tasks.update_status(persisted, AnalysisTaskStatus.FAILED.value, reason="The analytical task could not be completed safely.")
                await self.session.commit()
                failed.add(task_code)
                code = getattr(exc, "code", "ANALYSIS_TOOL_EXECUTION_FAILED")
                detail = getattr(exc, "internal_detail", None) or getattr(exc, "detail", None) or str(exc)
                failure_codes.add(code)
                failure_details.append(f"{task_code}: {detail}")
                logger.warning(
                    "Analytical task failed analysis_run_id=%s task_code=%s analysis_type=%s error_code=%s reason=%s",
                    run.id,
                    task_code,
                    task.get("analysis_type"),
                    code,
                    detail,
                    extra={
                        "analysis_run_id": str(run.id),
                        "task_code": task_code,
                        "analysis_type": task.get("analysis_type"),
                        "error_code": code,
                        "validation_reason": detail,
                    },
                )
        if failed:
            self.warnings.append(f"{len(failed)} planned step(s) could not be completed. The answer covers only the successful calculations.")
            priority = ["EVIDENCE_PERSISTENCE_FAILED", "ANALYSIS_METHOD_NOT_SUPPORTED", "ANALYSIS_TOOL_VALIDATION_FAILED", "ANALYSIS_TOOL_EXECUTION_FAILED"]
            code = next((item for item in priority if item in failure_codes), "ANALYSIS_TOOL_EXECUTION_FAILED")
            if not evidence_output or "EVIDENCE_PERSISTENCE_FAILED" in failure_codes:
                raise TaskExecutionFailure(code, " | ".join(failure_details))
            logger.warning(
                "Analysis continuing with partial evidence analysis_run_id=%s completed_tasks=%s failed_tasks=%s reasons=%s",
                run.id,
                len(evidence_output),
                len(failed),
                " | ".join(failure_details),
                extra={
                    "analysis_run_id": str(run.id),
                    "completed_task_count": len(evidence_output),
                    "failed_task_count": len(failed),
                    "partial_failure_reasons": failure_details,
                },
            )
        return evidence_output

    @traced("tools.statistics")
    async def execute_statistics(self, *, run: AnalysisRun, plan_output: AnalysisPlanOutput, profile: dict[str, Any], run_agent: AgentRunner) -> list[dict[str, Any]]:
        if self.dataframe is None or self.plan is None: return []
        columns = [column["name"] for column in profile["columns"]]
        candidates = [task for task in self.task_specs if task["task_code"] in self.evidence_by_task and task["analysis_type"] in {"statistical_test", "correlation", "regression"}]
        output = []
        for task in candidates:
            payload = {key: value for key, value in task.items() if key != "id"}
            async def invoke(payload=payload):
                return await self.validator.run(provider=run.llm_provider, task=payload, verified_columns=columns, dataframe=self.dataframe)
            result = await run_agent(f"statistical_validator:{task['task_code']}", {"task": payload}, invoke)
            evidence = self.evidence_by_task.get(task["task_code"])
            try:
                item = await self.stat_service.create(run_id=run.id, task_id=task["id"], evidence_id=evidence.id if evidence else None, content=result.content)
            except StatisticalValidationPersistenceError:
                await self.session.rollback()
                raise
            await self.session.commit()
            output.append({"evidence_code": evidence.evidence_code if evidence else None, "method_requested": item.method_requested, "method": item.method_used, "p_value": item.p_value, "effect_size": item.effect_size, "confidence_interval": item.confidence_interval, "assumptions": item.assumptions, "is_significant": item.is_significant, "is_valid": item.is_valid, "interpretation": item.interpretation, "warnings": item.warnings})
        return output

    @staticmethod
    def format_response(evidence: list[dict[str, Any]], validations: list[dict[str, Any]]) -> str:
        lines = ["Analysis complete", "", "Key findings:"]
        for index, item in enumerate(evidence, 1):
            lines.append(f"{index}. {item['interpretation']}")
        if validations:
            lines.extend(["", "Statistical validation:"])
            lines.extend(f"- {item['interpretation']}" for item in validations)
        limitations = sorted({warning for item in evidence for warning in item["limitations"]} | {warning for item in validations for warning in item["warnings"]})
        if limitations:
            lines.extend(["", "Data notes:", *[f"- {item}" for item in limitations]])
        return "\n".join(lines)

    @staticmethod
    def _topological_tasks(tasks: list[AnalysisTask]) -> list[AnalysisTask]:
        remaining = {task.task_code: task for task in tasks}; completed: set[str] = set(); ordered = []
        while remaining:
            ready = sorted((task for task in remaining.values() if set(task.depends_on) <= completed), key=lambda item: (item.priority, item.task_code))
            if not ready: raise TaskExecutionFailure("ANALYSIS_TOOL_VALIDATION_FAILED")
            for task in ready: ordered.append(task); completed.add(task.task_code); remaining.pop(task.task_code)
        return ordered

    @staticmethod
    def _task_payload(task):
        return {"task_code": task.task_code, "objective": task.objective, "analysis_type": task.analysis_type, "method": task.method, "required_columns": task.required_columns, "depends_on": task.depends_on, "priority": task.priority}
    @staticmethod
    def _evidence_dict(item):
        return {
            "evidence_code": item.evidence_code,
            "task_id": str(item.analysis_task_id),
            "method": item.method,
            "columns_used": item.columns_used,
            "operation": item.operation,
            "filters": item.filters,
            "result": item.result,
            "interpretation": item.interpretation,
            "limitations": item.limitations,
        }
