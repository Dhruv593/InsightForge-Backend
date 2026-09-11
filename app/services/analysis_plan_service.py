from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import (
    AnalysisPlanStatus,
    AnalysisTaskStatus,
    AnalysisTaskType,
    MAX_ANALYSIS_TASKS,
)
from app.core.exceptions import AnalysisPlanNotFoundError, AnalysisPlanPersistenceError
from app.models.analysis_plan import AnalysisPlan
from app.models.analysis_task import AnalysisTask
from app.repositories.analysis_plan_repository import AnalysisPlanRepository
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.analysis_task_repository import AnalysisTaskRepository
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.profile_interpretation import ProfileInterpretation
from app.schemas.supervisor import SupervisorDecision


class AgentSemanticValidationError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class AnalysisPlanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.plans = AnalysisPlanRepository(session)
        self.tasks = AnalysisTaskRepository(session)
        self.runs = AnalysisRunRepository(session)

    @staticmethod
    def validate_supervisor(
        decision: SupervisorDecision,
        available_columns: set[str],
    ) -> SupervisorDecision:
        referenced = set(decision.target_metrics) | set(decision.relevant_dimensions)
        unknown = sorted(referenced - available_columns)
        if unknown:
            raise AgentSemanticValidationError(
                "AGENT_SUPERVISOR_FAILED",
                "The supervisor referenced columns that are not present in the dataset.",
            )
        if not decision.can_answer_with_available_data and not decision.missing_requirements:
            raise AgentSemanticValidationError(
                "AGENT_SUPERVISOR_FAILED",
                "An unsupported request must explain what information is missing.",
            )
        return decision

    @staticmethod
    def validate_profile_interpretation(
        interpretation: ProfileInterpretation,
        available_columns: set[str],
    ) -> ProfileInterpretation:
        referenced = {
            item.name for item in interpretation.relevant_columns
        } | set(interpretation.usable_date_columns) | set(interpretation.excluded_columns)
        if referenced - available_columns:
            raise AgentSemanticValidationError(
                "AGENT_PROFILE_INTERPRETER_FAILED",
                "The profile interpretation referenced columns that are not present in the dataset.",
            )
        return interpretation

    @staticmethod
    def validate_plan(
        output: AnalysisPlanOutput,
        available_columns: set[str],
    ) -> AnalysisPlanOutput:
        if len(output.tasks) > MAX_ANALYSIS_TASKS:
            raise AgentSemanticValidationError(
                "ANALYSIS_PLAN_INVALID",
                f"The analysis plan may contain at most {MAX_ANALYSIS_TASKS} tasks.",
            )
        if output.target_metric and output.target_metric not in available_columns:
            raise AgentSemanticValidationError(
                "ANALYSIS_PLAN_INVALID",
                "The analysis plan target metric is not present in the dataset.",
            )
        codes = [task.task_code for task in output.tasks]
        if len(codes) != len(set(codes)):
            raise AgentSemanticValidationError(
                "ANALYSIS_PLAN_INVALID", "Analysis task codes must be unique."
            )
        code_set = set(codes)
        allowed_types = {item.value for item in AnalysisTaskType}
        for task in output.tasks:
            if task.analysis_type not in allowed_types:
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "The plan contains an unsupported analysis type."
                )
            if len(task.required_columns) != len(set(task.required_columns)):
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "Task required columns must be unique."
                )
            if set(task.required_columns) - available_columns:
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID",
                    "An analysis task referenced columns that are not present in the dataset.",
                )
            if task.task_code in task.depends_on:
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "An analysis task cannot depend on itself."
                )
            if set(task.depends_on) - code_set:
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "An analysis task has an unknown dependency."
                )
            if len(task.depends_on) != len(set(task.depends_on)):
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "Task dependencies must be unique."
                )
        AnalysisPlanService._validate_acyclic(output)
        return output

    @staticmethod
    def _validate_acyclic(output: AnalysisPlanOutput) -> None:
        dependencies = {task.task_code: task.depends_on for task in output.tasks}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(code: str) -> None:
            if code in visiting:
                raise AgentSemanticValidationError(
                    "ANALYSIS_PLAN_INVALID", "Analysis task dependencies contain a cycle."
                )
            if code in visited:
                return
            visiting.add(code)
            for dependency in dependencies[code]:
                visit(dependency)
            visiting.remove(code)
            visited.add(code)

        for code in dependencies:
            visit(code)

    async def persist_validated(
        self,
        analysis_run_id: UUID,
        output: AnalysisPlanOutput,
        available_columns: set[str],
    ) -> AnalysisPlan:
        output = self.validate_plan(output, available_columns)
        plan = AnalysisPlan(
            analysis_run_id=analysis_run_id,
            question_type=output.question_type,
            objective=output.objective,
            target_metric=output.target_metric,
            analysis_strategy=output.analysis_strategy,
            requires_statistics=output.requires_statistics,
            requires_visualization=output.requires_visualization,
            completion_criteria=output.completion_criteria,
            limitations=output.limitations,
            status=AnalysisPlanStatus.VALIDATED.value,
        )
        try:
            await self.plans.create(plan)
            await self.tasks.create_many(
                [
                    AnalysisTask(
                        analysis_plan_id=plan.id,
                        task_code=task.task_code,
                        objective=task.objective,
                        analysis_type=task.analysis_type,
                        method=task.method,
                        required_columns=task.required_columns,
                        depends_on=task.depends_on,
                        priority=task.priority,
                        status=AnalysisTaskStatus.PENDING.value,
                    )
                    for task in output.tasks
                ]
            )
            return plan
        except SQLAlchemyError as exc:
            raise AnalysisPlanPersistenceError from exc

    async def get_for_run(self, analysis_run_id: UUID, user_id: UUID) -> AnalysisPlan:
        run = await self.runs.get_by_id_for_user(analysis_run_id, user_id)
        if run is None:
            from app.core.exceptions import AnalysisRunNotFoundError
            raise AnalysisRunNotFoundError
        plan = await self.plans.get_by_analysis_run_id(run.id)
        if plan is None:
            raise AnalysisPlanNotFoundError
        return plan
