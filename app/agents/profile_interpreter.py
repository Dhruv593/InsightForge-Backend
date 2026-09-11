from typing import Any

from app.schemas.llm import LLMResult, LLMUsage
from app.schemas.profile_interpretation import ProfileInterpretation, RelevantColumn
from app.schemas.supervisor import SupervisorDecision
from app.services.analysis_plan_service import AnalysisPlanService
from app.services.llm.llm_service import LLMService

class ProfileInterpreterAgent:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def run(
        self,
        *,
        provider: str,
        query: str,
        supervisor_decision: SupervisorDecision,
        dataset_context: dict[str, Any],
    ) -> LLMResult:
        metrics = set(supervisor_decision.target_metrics)
        dimensions = set(supervisor_decision.relevant_dimensions)
        query_lower = query.lower()
        selected = []
        date_columns = []
        for column in dataset_context["columns"]:
            name = column["name"]
            inferred = str(column.get("inferred_type", "unknown"))
            lowered_type = inferred.lower()
            is_date = "date" in lowered_type or "time" in lowered_type or "date" in name.lower()
            if is_date:
                date_columns.append(name)
            if name not in metrics and name not in dimensions and name.lower() not in query_lower and not (is_date and any(token in query_lower for token in ("month", "week", "quarter", "year", "trend", "time"))):
                continue
            role = "metric" if name in metrics else "dimension" if name in dimensions else "date" if is_date else "potential_driver" if any(token in lowered_type for token in ("int", "float", "number", "decimal")) else "other"
            selected.append(RelevantColumn(name=name, role=role, inferred_type=inferred, relevance_reason="Selected from the validated supervisor decision and dataset profile."))
        if not selected:
            selected = [RelevantColumn(name=column["name"], role="date" if column["name"] in date_columns else "other", inferred_type=str(column.get("inferred_type", "unknown")), relevance_reason="Available verified dataset column.") for column in dataset_context["columns"]]
        relevant_names = {item.name for item in selected}
        interpretation = AnalysisPlanService.validate_profile_interpretation(
            ProfileInterpretation(
                relevant_columns=selected,
                usable_date_columns=[name for name in date_columns if name in relevant_names],
                data_quality_constraints=[item["message"] for item in dataset_context.get("quality_issues", []) if item.get("message")],
                excluded_columns=[column["name"] for column in dataset_context["columns"] if column["name"] not in relevant_names],
                analysis_warnings=[],
            ),
            {column["name"] for column in dataset_context["columns"]},
        )
        return LLMResult(provider=provider, model="deterministic-profile", content=interpretation.model_dump(mode="json"), usage=LLMUsage(), latency_ms=0)
