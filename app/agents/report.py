import json
from typing import Any

from app.schemas.llm import LLMMessage, LLMResult
from app.schemas.report import FinalReportOutput
from app.services.llm.llm_service import LLMService

PROMPT = """You are the Report Agent for InsightForge. Prepare the final analytical response using only Critic-accepted claims and their support. Do not introduce calculations, claims, rejected findings, or causal language not explicitly supported. Separate findings, statistical findings, data-quality notes, limitations, and practical qualitative recommendations. Recommendation numbers must already exist in evidence. Every key finding must identify its accepted claim code and evidence codes. Return only the required schema."""


class ReportAgent:
    def __init__(self, llm_service: LLMService) -> None: self.llm = llm_service

    async def run(self, *, provider: str, query: str, claims: list[dict[str, Any]], evidence: list[dict[str, Any]], validations: list[dict[str, Any]], quality_warnings: list[dict[str, Any]], charts: list[dict[str, Any]]) -> LLMResult:
        payload = {"query": query, "accepted_claims": claims, "supporting_evidence": evidence, "statistical_validations": validations, "data_quality_warnings": quality_warnings, "chart_specs": charts}
        return await self.llm.generate_structured(provider=provider, messages=[LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False))], response_model=FinalReportOutput)
