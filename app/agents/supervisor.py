import json
from typing import Any

from app.schemas.llm import LLMMessage, LLMResult
from app.schemas.supervisor import SupervisorDecision
from app.services.analysis_plan_service import AnalysisPlanService
from app.services.llm.llm_service import LLMService

SUPERVISOR_PROMPT = """You are the Supervisor Agent for InsightForge.

Classify the user's analytical request and determine whether the verified dataset can support it. Do not calculate numerical results, answer the business question, invent columns, or invent dataset content. Use only the user's question, verified bounded profile, and recent conversation context.

Determine the query type, objective, target metrics, relevant dimensions, whether statistics may be needed, whether visualization would be useful, and whether sufficient information exists. If required information is absent, mark the request unsupported, leave invented/nonexistent columns out of target fields, and explicitly describe the missing information. Return only the required structured schema."""


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
            response_model=SupervisorDecision,
        )
        decision = AnalysisPlanService.validate_supervisor(
            SupervisorDecision.model_validate(result.content),
            {column["name"] for column in dataset_context["columns"]},
        )
        return result.model_copy(update={"content": decision.model_dump(mode="json")})
