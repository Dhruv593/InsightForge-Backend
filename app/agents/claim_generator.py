import json
from typing import Any

from app.schemas.claim import ClaimGenerationOutput
from app.schemas.llm import LLMMessage, LLMResult
from app.services.llm.llm_service import LLMService

PROMPT = """You are the InsightForge Claim Generation Agent. Turn deterministic analytical evidence into a small set of concise candidate findings. Use only supplied evidence and statistical validations. Do not calculate or invent values or explanations. Do not claim causation from correlation or observational comparisons. Do not hide limitations. Every claim must reference its supporting evidence. Use sequential claim_code values exactly as C1, C2, C3, and so on. Copy evidence_codes exactly from the supplied evidence records. Return one JSON object with a claims array and no additional fields, prose, or Markdown."""


class ClaimGeneratorAgent:
    def __init__(self, llm_service: LLMService) -> None: self.llm = llm_service

    async def run(self, *, provider: str, query: str, evidence: list[dict[str, Any]], validations: list[dict[str, Any]]) -> LLMResult:
        return await self.llm.generate_structured(provider=provider, messages=[LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=json.dumps({"query": query, "evidence": evidence, "statistical_validations": validations}, ensure_ascii=False))], response_model=ClaimGenerationOutput)
