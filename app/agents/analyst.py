import json
import logging
import re
from typing import Any

import pandas as pd

from app.schemas.analysis_execution import AnalysisExecutionRequest, EvidenceInterpretation
from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.services.llm.llm_service import LLMService
from app.services.llm.base import LLMProviderError
from app.tools.analytics import AnalyticsToolRegistry, ToolValidationError

INTERPRET_PROMPT = """Explain the supplied analytical result for a small business owner with no technical background. Write short sentences, one finding per line. Use only values present in the result. Do not output JSON, Markdown headings, or a schema. Explain patterns without claiming they prove a cause. Describe unusual values, blank entries, and repeated records in everyday language; avoid IQR, deterministic, metadata, tool results, and other implementation jargon. Keep relevant limitations, explain their practical effect, and never invent numbers."""

logger = logging.getLogger(__name__)

TASK_TOOL_MAP = {
    "aggregation": {"groupby_aggregate"},
    "comparison": {"groupby_aggregate", "calculate_percentage_change", "time_series_aggregate"},
    "segmentation": {"groupby_aggregate", "calculate_contribution"},
    "correlation": {"calculate_correlation"},
    "statistical_test": {"groupby_aggregate", "calculate_correlation", "distribution_summary"},
    "time_series": {"time_series_aggregate"},
    "distribution": {"distribution_summary"},
    "data_quality": {"filter_dataset", "distribution_summary"},
}


class NumericGroundingError(Exception): pass


class AnalystAgent:
    def __init__(self, llm_service: LLMService, tools: AnalyticsToolRegistry | None = None) -> None:
        self.llm = llm_service
        self.tools = tools or AnalyticsToolRegistry()

    async def run(self, *, provider: str, query: str, task: dict[str, Any], verified_columns: list[str], profile_metadata: dict[str, Any], dataframe: pd.DataFrame, prior_evidence: list[dict[str, Any]]) -> LLMResult:
        request = self._fallback_request(query, task, profile_metadata, dataframe)
        tool_result = self._execute_selection(dataframe, request, task)
        logger.info(
            "Deterministic analytical tool selected task_code=%s analysis_type=%s tool=%s",
            task.get("task_code"), task.get("analysis_type"), request.tool,
            extra={"task_code": task.get("task_code"), "analysis_type": task.get("analysis_type"), "tool": request.tool},
        )

        interpretation_result: LLMResult | None = None
        try:
            interpretation_result = await self.llm.generate_text(
                provider=provider,
                messages=[LLMMessage(role="system", content=INTERPRET_PROMPT), LLMMessage(role="user", content=json.dumps({"task_objective": task["objective"], "interpretation_focus": request.interpretation_focus, "tool_result": tool_result.model_dump(mode="json")}, ensure_ascii=False))],
            )
            text = str(interpretation_result.content.get("text", "")).strip()
            if not text:
                raise ValueError("The interpretation response was empty.")
            interpretation = EvidenceInterpretation(interpretation=text, limitations=[])
            grounded_source = tool_result.model_dump(mode="json")
            self._validate_numeric_grounding(interpretation.interpretation, grounded_source)
        except (LLMProviderError, NumericGroundingError, ValueError, NotImplementedError) as exc:
            interpretation = self._fallback_interpretation(task, tool_result)
            logger.warning(
                "Using deterministic evidence interpretation fallback task_code=%s reason=%s",
                task.get("task_code"), exc,
                extra={"task_code": task.get("task_code"), "fallback_reason": str(exc)},
            )

        used_results = [interpretation_result] if interpretation_result else []
        usage = self._usage(*used_results) if used_results else LLMUsage()
        return LLMResult(
            provider=provider,
            model=interpretation_result.model if interpretation_result else f"{provider}-deterministic-analysis",
            content={"selection": request.model_dump(mode="json", exclude_none=True), "tool_result": tool_result.model_dump(mode="json"), "interpretation": interpretation.model_dump(mode="json")},
            usage=usage,
            latency_ms=sum(item.latency_ms for item in used_results),
        )

    @staticmethod
    def _fallback_request(query: str, task: dict[str, Any], profile: dict[str, Any], dataframe: pd.DataFrame) -> AnalysisExecutionRequest:
        verified = [name for name in task.get("required_columns", []) if name in dataframe.columns]
        if not verified:
            verified = list(dataframe.columns)
        types = {item.get("name"): str(item.get("inferred_type", "")).lower() for item in profile.get("columns", [])}

        def numeric(name: str) -> bool:
            source = dataframe[name]
            return pd.api.types.is_numeric_dtype(source) or pd.to_numeric(source, errors="coerce").notna().sum() == source.notna().sum()

        numeric_columns = [name for name in verified if numeric(name)]
        date_columns = [name for name in verified if "date" in types.get(name, "") or "time" in types.get(name, "")]
        if not date_columns:
            date_columns = [name for name in verified if "date" in name.lower()]
        categorical = [name for name in verified if name not in numeric_columns and name not in date_columns]
        metric = numeric_columns[0] if numeric_columns else None
        analysis_type = task.get("analysis_type")
        focus = f"Complete the validated task: {task.get('objective', query)}"

        if analysis_type == "time_series" and date_columns and metric:
            frequency = "yearly" if re.search(r"\byear", query, re.I) else "quarterly" if re.search(r"\bquarter", query, re.I) else "weekly" if re.search(r"\bweek", query, re.I) else "daily" if re.search(r"\bday|daily", query, re.I) else "monthly"
            return AnalysisExecutionRequest(tool="time_series_aggregate", parameters={"date_column": date_columns[0], "metric": metric, "frequency": frequency, "aggregation": "sum"}, interpretation_focus=focus)
        if analysis_type == "comparison" and date_columns and metric:
            frequency = "yearly" if re.search(r"\byear", query, re.I) else "quarterly" if re.search(r"\bquarter", query, re.I) else "weekly" if re.search(r"\bweek", query, re.I) else "daily" if re.search(r"\bday|daily", query, re.I) else "monthly"
            return AnalysisExecutionRequest(tool="time_series_aggregate", parameters={"date_column": date_columns[0], "metric": metric, "frequency": frequency, "aggregation": "sum"}, interpretation_focus=focus)
        if analysis_type == "correlation" and len(numeric_columns) >= 2:
            return AnalysisExecutionRequest(tool="calculate_correlation", parameters={"x": numeric_columns[0], "y": numeric_columns[1], "method": "pearson"}, interpretation_focus=focus)
        if analysis_type == "distribution" and metric:
            return AnalysisExecutionRequest(tool="distribution_summary", parameters={"column": metric}, interpretation_focus=focus)
        if analysis_type in {"aggregation", "comparison", "segmentation", "statistical_test"} and categorical and metric:
            return AnalysisExecutionRequest(tool="groupby_aggregate", parameters={"group_by": [categorical[0]], "metric": metric, "aggregation": "sum", "sort": "desc"}, interpretation_focus=focus)
        if analysis_type == "statistical_test" and metric:
            return AnalysisExecutionRequest(tool="distribution_summary", parameters={"column": metric}, interpretation_focus=focus)
        if analysis_type == "data_quality":
            return AnalysisExecutionRequest(tool="filter_dataset", parameters={"columns": verified, "limit": 100}, interpretation_focus=focus)
        raise ToolValidationError(f"No safe deterministic fallback is available for analysis type '{analysis_type}' with required columns {verified}.")

    @staticmethod
    def _fallback_interpretation(task: dict[str, Any], tool_result) -> EvidenceInterpretation:
        result = tool_result.result
        if isinstance(result, list):
            rows = []
            for row in result[:8]:
                if isinstance(row, dict):
                    rows.append(', '.join(f"{str(key).replace('_', ' ')}: {value}" for key, value in row.items() if value is not None and not isinstance(value, (dict, list))))
            detail = '; '.join(filter(None, rows)) or 'No matching records were returned.'
            if len(result) > 8:
                detail += ' (Showing the first 8 result rows.)'
        elif isinstance(result, dict):
            detail = '; '.join(f"{str(key).replace('_', ' ')}: {value}" for key, value in result.items() if value is not None and isinstance(value, (int, float, str)) and not isinstance(value, bool)) or 'No simple numerical summary is available for this result.'
        else:
            detail = f"The deterministic {tool_result.tool} operation completed successfully."
        return EvidenceInterpretation(
            interpretation=detail,
            limitations=["An explanation could not be prepared. These values come directly from the completed calculation."],
        )

    def _execute_selection(
        self,
        dataframe: pd.DataFrame,
        request: AnalysisExecutionRequest,
        task: dict[str, Any],
    ):
        allowed_tools = TASK_TOOL_MAP.get(task.get("analysis_type"), set())
        if request.tool not in allowed_tools:
            raise ToolValidationError(
                f"Tool '{request.tool}' is incompatible with analysis type '{task.get('analysis_type')}'. "
                f"Allowed tools: {', '.join(sorted(allowed_tools)) or 'none'}."
            )
        parameters = request.parameters.model_dump(mode="json", exclude_none=True)
        return self.tools.execute(dataframe, request.tool, parameters)

    @staticmethod
    def _usage(*results: LLMResult) -> LLMUsage:
        def total(field):
            values = [getattr(result.usage, field) for result in results]
            return sum(value for value in values if value is not None) if any(value is not None for value in values) else None
        return LLMUsage(prompt_tokens=total("prompt_tokens"), completion_tokens=total("completion_tokens"), total_tokens=total("total_tokens"))

    @staticmethod
    def _validate_numeric_grounding(text: str, result: object) -> None:
        def collect(value: object) -> list[float]:
            if isinstance(value, bool): return []
            if isinstance(value, (int, float)): return [float(value)]
            if isinstance(value, str): return [float(token) for token in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", value.replace(",", ""))]
            if isinstance(value, dict): return [number for item in value.values() for number in collect(item)]
            if isinstance(value, list): return [number for item in value for number in collect(item)]
            return []
        allowed = collect(result)
        for token in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", text.replace(",", "")):
            number = float(token)
            if not any(
                abs(number - candidate) <= max(1e-6, abs(candidate) * 1e-4)
                for value in allowed
                for candidate in ((value, value * 100) if abs(value) <= 1 else (value,))
            ):
                raise NumericGroundingError("Interpretation introduced an ungrounded numeric value.")
