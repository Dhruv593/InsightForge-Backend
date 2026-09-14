import json
from typing import Any

from app.schemas.claim import ClaimGenerationOutput
from app.schemas.llm import LLMMessage, LLMResult
from app.services.llm.llm_service import LLMService

from app.prompts.claim_generator_prompt import SYSTEM_PROMPT as PROMPT, OUTPUT_MODEL


class ClaimGeneratorAgent:
    def __init__(self, llm_service: LLMService) -> None: self.llm = llm_service

    async def run(self, *, provider: str, query: str, evidence: list[dict[str, Any]], validations: list[dict[str, Any]]) -> LLMResult:
        return await self.llm.generate_structured(provider=provider, messages=[LLMMessage(role="system", content=PROMPT), LLMMessage(role="user", content=json.dumps({"query": query, "evidence": evidence, "statistical_validations": validations}, ensure_ascii=False))], response_model=OUTPUT_MODEL)
