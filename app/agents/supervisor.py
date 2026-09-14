import json
from typing import Any

from app.schemas.llm import LLMMessage, LLMResult
from app.schemas.supervisor import SupervisorDecision
from app.services.analysis_plan_service import AnalysisPlanService
from app.services.llm.llm_service import LLMService

from app.prompts.supervisor_prompt import SYSTEM_PROMPT as SUPERVISOR_PROMPT, OUTPUT_MODEL


class SupervisorAgent:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm_service = llm_service

    async def run(
        self,
        *,
        provider: str,
        query: str,
        dataset_context: dict[str, Any],
        conversation_context: list[dict[str, str]],
    ) -> LLMResult:
        result = await self.llm_service.generate_structured(
            provider=provider,
            messages=[
                LLMMessage(role="system", content=SUPERVISOR_PROMPT),
                LLMMessage(role="user", content=json.dumps({
                    "query": query,
                    "dataset": dataset_context,
                    "recent_conversation": conversation_context,
                }, ensure_ascii=False)),
            ],
            response_model=OUTPUT_MODEL,
        )
        decision = AnalysisPlanService.validate_supervisor(
            SupervisorDecision.model_validate(result.content),
            {column["name"] for column in dataset_context["columns"]},
        )
        return result.model_copy(update={"content": decision.model_dump(mode="json")})
