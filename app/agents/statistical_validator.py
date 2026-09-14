import json
from typing import Any

import pandas as pd

from app.agents.analyst import AnalystAgent, NumericGroundingError
from app.schemas.llm import LLMMessage, LLMResult
from app.schemas.llm import LLMUsage
from app.schemas.statistical_validation import StatisticalValidationRequest
from app.services.llm.base import LLMProviderError
from app.services.llm.llm_service import LLMService
from app.tools.statistics import StatisticalToolRegistry

from app.prompts.statistical_validator_prompt import SYSTEM_PROMPT as INTERPRET_PROMPT


class StatisticalValidatorAgent:
    def __init__(self, llm_service: LLMService, tools: StatisticalToolRegistry | None = None) -> None:
        self.llm = llm_service
        self.tools = tools or StatisticalToolRegistry()

    async def run(self, *, provider: str, task: dict[str, Any], verified_columns: list[str], dataframe: pd.DataFrame) -> LLMResult:
        request = self._select_request(task, verified_columns, dataframe)
        result = self.tools.execute(dataframe.copy(deep=False), request)
        interpreted = None
        try:
            interpreted = await self.llm.generate_text(provider=provider, messages=[LLMMessage(role="system", content=INTERPRET_PROMPT), LLMMessage(role="user", content=json.dumps({"task_objective": task["objective"], "statistical_result": result.model_dump(mode="json")}, ensure_ascii=False))])
            interpretation = str(interpreted.content.get("text", "")).strip()
            if not interpretation:
                raise ValueError("The statistical interpretation was empty.")
            AnalystAgent._validate_numeric_grounding(interpretation, result.model_dump(mode="json"))
        except (LLMProviderError, NumericGroundingError, ValueError, NotImplementedError):
            interpretation = f"The deterministic {result.method_used} validation completed. Review the saved statistic, significance result, effect size, assumptions, and warnings together."
        return LLMResult(provider=provider, model=interpreted.model if interpreted else f"{provider}-deterministic-statistics", content={"request": request.model_dump(mode="json"), "result": result.model_dump(mode="json"), "interpretation": interpretation}, usage=interpreted.usage if interpreted else LLMUsage(), latency_ms=interpreted.latency_ms if interpreted else 0)

    @staticmethod
    def _select_request(task: dict[str, Any], verified_columns: list[str], dataframe: pd.DataFrame) -> StatisticalValidationRequest:
        required = [name for name in task.get("required_columns", []) if name in verified_columns and name in dataframe.columns]
        if len(required) < 2:
            required = [name for name in verified_columns if name in dataframe.columns]
        numeric = [name for name in required if pd.api.types.is_numeric_dtype(dataframe[name]) or pd.to_numeric(dataframe[name], errors="coerce").notna().sum() == dataframe[name].notna().sum()]
        categorical = [name for name in required if name not in numeric]
        method_hint = str(task.get("method", "")).lower()
        if len(numeric) >= 2:
            test_type = "spearman" if "spearman" in method_hint else "pearson"
            columns, group = numeric[:2], None
        elif categorical and numeric:
            group = categorical[0]
            group_count = int(dataframe[group].dropna().nunique())
            test_type = "anova" if group_count > 2 else "mann_whitney_u" if "mann" in method_hint or "nonparametric" in method_hint else "welch_t_test"
            columns = [group, numeric[0]]
        elif len(categorical) >= 2:
            test_type, columns, group = "chi_square", categorical[:2], None
        else:
            raise ValueError(f"No safe statistical test can be selected from required columns {required}.")
        return StatisticalValidationRequest(method_requested=task.get("method") or task.get("objective") or "deterministic statistical validation", test_type=test_type, columns=columns, group_column=group, assumptions_to_check=["sample_size", "missing_values"])
