import json
from typing import Any

from app.schemas.claim_review import ClaimEvaluation
from app.schemas.llm import LLMMessage, LLMResult
from app.services.llm.llm_service import LLMService

PROMPT = """You are the Critic Agent for InsightForge. Aggressively verify whether the candidate analytical claim is justified by the supplied deterministic evidence. Check numeric support, overgeneralization, causal language, contradictory evidence, sample size, statistical assumptions, effect size, extrapolation, and data-quality limitations. Do not calculate or invent evidence. If cautious wording makes the claim valid, return corrected wording. Return only the required schema."""


class CriticAgent:
    def __init__(self, llm_service: LLMService) -> None: self.llm = llm_service

    async def run(self, *, provider: str, query: str, claim: dict[str, Any], evidence: list[dict[str, Any]], validations: list[dict[str, Any]], quality_warnings: list[dict[str, Any]]) -> LLMResult:
        payload = {"query": query, "claim": claim, "supporting_evidence": evidence, "linked_statistical_validations": validations, "data_quality_warnings": quality_warnings}
        return await self.llm.generate_structured(provider=provider, messages=[LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False))], response_model=ClaimEvaluation)
