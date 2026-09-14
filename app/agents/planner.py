import json
from typing import Any
import logging
from pydantic import ValidationError

from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.schemas.profile_interpretation import ProfileInterpretation
from app.schemas.supervisor import SupervisorDecision
from app.services.analysis_plan_service import AnalysisPlanService, AgentSemanticValidationError
from app.services.llm.base import LLMProviderError
from app.services.llm.llm_service import LLMService

from app.prompts.planner_prompt import SYSTEM_PROMPT as PLANNER_PROMPT, OUTPUT_MODEL



class PlannerAgent:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def run(
        self,
        *,
        provider: str,
        query: str,
        supervisor_decision: SupervisorDecision,
        profile_interpretation: ProfileInterpretation,
        verified_columns: list[str],
    ) -> LLMResult:
        try:
            return await self._plan(provider, query, supervisor_decision, profile_interpretation, verified_columns)
        except (LLMProviderError, ValidationError, AgentSemanticValidationError):
            logging.getLogger(__name__).warning("Using limited metric-summary plan after planner failure provider=%s", provider)
            metrics = [column.name for column in profile_interpretation.relevant_columns
                       if column.name in supervisor_decision.target_metrics and column.name in verified_columns
                       and column.inferred_type.lower() in {"numeric", "integer", "float", "number", "decimal", "int", "int64", "float64"}][:3]
            if not metrics:
                raise
            plan = AnalysisPlanOutput(
                question_type="descriptive", objective="Provide an overall summary of the requested metrics.",
                target_metric=metrics[0], analysis_strategy="Calculate whole-dataset metric summaries from verified columns.",
                requires_statistics=False, requires_visualization=False,
                tasks=[{"task_code": f"RECOVERY_{index}", "objective": f"Summarize {metric} across the entire dataset.",
                        "analysis_type": "distribution", "required_columns": [metric], "method": "distribution_summary",
                        "priority": index, "depends_on": []} for index, metric in enumerate(metrics, 1)],
                completion_criteria=["Return only successfully calculated summaries."],
                limitations=["The detailed request could not be planned. These are overall summaries across the entire dataset; requested filters, comparisons, and time periods have not been applied."],
            )
            AnalysisPlanService.validate_plan(plan, set(verified_columns))
            return LLMResult(provider=provider, model="local-summary-plan", content=plan.model_dump(mode="json"), usage=LLMUsage(), latency_ms=0)

    async def _plan(self, provider, query, supervisor_decision, profile_interpretation, verified_columns):
        result = await self.llm_service.generate_structured(
            provider=provider,
            messages=[
                LLMMessage(role="system", content=PLANNER_PROMPT),
                LLMMessage(role="user", content=json.dumps({
                    "query": query,
                    "supervisor_decision": supervisor_decision.model_dump(mode="json"),
                    "profile_interpretation": profile_interpretation.model_dump(mode="json"),
                    "verified_columns": verified_columns,
                }, ensure_ascii=False)),
            ],
            response_model=OUTPUT_MODEL,
        )
        plan = AnalysisPlanService.validate_plan(
            AnalysisPlanOutput.model_validate(result.content),
            set(verified_columns),
        )
        return result.model_copy(update={"content": plan.model_dump(mode="json")})
