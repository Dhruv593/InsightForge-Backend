import json
from typing import Any

from app.schemas.chart import VisualizationOutput
from app.schemas.llm import LLMMessage, LLMResult
from app.services.llm.llm_service import LLMService

PROMPT = """You are the Visualization Agent for InsightForge. Proactively visualize useful accepted findings even when the user does not name a chart. Use only accepted claims and supporting evidence; never invent findings or calculate values. Select by analytical purpose, not a default bar chart: line for time trends; pie or donut for 2-6 mutually exclusive categories of a nonnegative additive total; horizontal bar for rankings or many categories; grouped bar for two categorical dimensions; heatmap for dense category comparisons; waterfall for contributions to change; scatter for paired numeric observations; histogram or boxplot only for actual observations, never aggregated summaries. Do not use pie for averages, negative values, or time trends. Respect explicit chart requests only when the evidence supports them. Prefer useful variety across different findings, not arbitrary variety. Return only the required schema. Use original dataset columns for axes; aggregated evidence may store the metric under 'value'. Return an empty charts list only when the evidence cannot safely support a useful visual."""


class VisualizationAgent:
    def __init__(self, llm_service: LLMService) -> None: self.llm = llm_service

    async def run(self, *, provider: str, query: str, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], columns: list[dict[str, Any]]) -> LLMResult:
        payload = {"query": query, "accepted_claims": claims, "supporting_evidence": evidence, "dataset_columns": columns}
        return await self.llm.generate_structured(provider=provider, messages=[LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False))], response_model=VisualizationOutput)
