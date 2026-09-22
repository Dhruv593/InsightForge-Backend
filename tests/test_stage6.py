from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from app.schemas.llm import LLMMessage, LLMResult, LLMUsage, PipelineTestResponse
from app.services.llm.base import BaseLLMProvider, LLMProviderError
from app.services.llm.llm_service import LLMService
from app.services.llm.gemini_provider import GeminiProvider

pytestmark = pytest.mark.anyio


class StubProvider(BaseLLMProvider):
    def __init__(self, provider_name: str, model: str) -> None:
        super().__init__(api_key="test-only", model=model, timeout_seconds=1)
        self.provider_name = provider_name
        self.mock_generate = AsyncMock(return_value=LLMResult(
            provider=provider_name,
            model=model,
            content={"message": "Context received.", "status": "success"},
            usage=LLMUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            latency_ms=12,
        ))

    async def generate_structured(self, *, messages, response_model) -> LLMResult:
        return await self.mock_generate(messages=messages, response_model=response_model)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key=None, gemini_model=None, groq_api_key=None,
        groq_model=None, openai_api_key=None, openai_model=None,
        anthropic_api_key=None, anthropic_model=None, anthropic_max_tokens=8192,
        llm_request_timeout_seconds=1,
    )


async def test_llm_service_routes_only_to_selected_provider() -> None:
    gemini = StubProvider("gemini", "gemini-test")
    groq = StubProvider("groq", "groq-test")
    service = LLMService(settings=_settings(), providers={"gemini": gemini, "groq": groq})
    result = await service.generate_structured(
        provider="groq",
        messages=[LLMMessage(role="user", content="Validate")],
        response_model=PipelineTestResponse,
    )
    assert result.provider == "groq"
    groq.mock_generate.assert_awaited_once()
    gemini.mock_generate.assert_not_awaited()


async def test_unsupported_provider_is_rejected_without_fallback() -> None:
    gemini = StubProvider("gemini", "gemini-test")
    service = LLMService(settings=_settings(), providers={"gemini": gemini})
    with pytest.raises(LLMProviderError):
        await service.generate_structured(
            provider="other",
            messages=[LLMMessage(role="user", content="Validate")],
            response_model=PipelineTestResponse,
        )
    gemini.mock_generate.assert_not_awaited()


async def test_gemini_uses_a_simplified_supported_json_schema() -> None:
    response = SimpleNamespace(
        parsed=PipelineTestResponse(message="Context received.", status="success"),
        usage_metadata=None,
    )
    async_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=AsyncMock(return_value=response)),
        aclose=AsyncMock(),
    )
    client = SimpleNamespace(aio=async_client)
    provider = GeminiProvider(
        api_key="test-only", model="gemini-test", timeout_seconds=1
    )

    with patch("app.services.llm.gemini_provider.genai.Client", return_value=client):
        result = await provider.generate_structured(
            messages=[LLMMessage(role="user", content="Validate")],
            response_model=PipelineTestResponse,
        )

    config = async_client.models.generate_content.await_args.kwargs["config"]
    assert config.response_schema is None
    assert config.response_json_schema == {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "status": {"type": "string", "enum": ["success"]},
        },
        "required": ["message", "status"],
    }
    assert result.content == {"message": "Context received.", "status": "success"}
