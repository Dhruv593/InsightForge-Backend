import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from app.schemas.llm import LLMMessage, PipelineTestResponse
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMProviderError
from app.services.llm.llm_service import LLMService
from app.services.llm.openai_provider import OpenAIProvider

pytestmark = pytest.mark.anyio


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


async def test_openai_structured_output_and_usage():
    output = json.dumps({"message": "Ready", "status": "success"})
    fake = FakeClient(FakeResponse({
        "output": [{"type": "message", "content": [{"type": "output_text", "text": output}]}],
        "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
    }))
    provider = OpenAIProvider(api_key="secret", model="gpt-test", timeout_seconds=5)
    with patch("app.services.llm.openai_provider.httpx.AsyncClient", return_value=fake):
        result = await provider.generate_structured(
            messages=[LLMMessage(role="system", content="Be accurate"), LLMMessage(role="user", content="Analyze")],
            response_model=PipelineTestResponse,
        )
    assert result.provider == "openai"
    assert result.content == {"message": "Ready", "status": "success"}
    assert result.usage.total_tokens == 14
    request = fake.request[1]
    assert request["json"]["store"] is False
    assert request["json"]["text"]["format"]["type"] == "json_schema"
    assert request["headers"]["Authorization"] == "Bearer secret"


async def test_anthropic_structured_output_and_system_message():
    output = json.dumps({"message": "Ready", "status": "success"})
    fake = FakeClient(FakeResponse({
        "content": [{"type": "text", "text": output}],
        "usage": {"input_tokens": 11, "output_tokens": 5},
    }))
    provider = AnthropicProvider(api_key="secret", model="claude-test", timeout_seconds=5, max_tokens=4096)
    with patch("app.services.llm.anthropic_provider.httpx.AsyncClient", return_value=fake):
        result = await provider.generate_structured(
            messages=[LLMMessage(role="system", content="Be accurate"), LLMMessage(role="user", content="Analyze")],
            response_model=PipelineTestResponse,
        )
    assert result.provider == "anthropic"
    assert result.content == {"message": "Ready", "status": "success"}
    assert result.usage.total_tokens == 16
    request = fake.request[1]
    assert request["json"]["system"] == "Be accurate"
    assert request["json"]["messages"] == [{"role": "user", "content": "Analyze"}]
    assert request["json"]["max_tokens"] == 4096
    assert request["json"]["output_config"]["format"]["type"] == "json_schema"
    assert request["headers"]["x-api-key"] == "secret"


@pytest.mark.parametrize("provider_class", [OpenAIProvider, AnthropicProvider])
@pytest.mark.parametrize("status,code", [(401, "LLM_AUTHENTICATION_FAILED"), (429, "LLM_RATE_LIMITED"), (503, "LLM_PROVIDER_UNAVAILABLE"), (400, "LLM_EXECUTION_FAILED")])
async def test_new_provider_http_errors_are_safe(provider_class, status, code):
    fake = FakeClient(FakeResponse({}, status_code=status))
    provider = provider_class(api_key="secret", model="test-model", timeout_seconds=5)
    module = "openai_provider" if provider_class is OpenAIProvider else "anthropic_provider"
    with patch(f"app.services.llm.{module}.httpx.AsyncClient", return_value=fake):
        with pytest.raises(LLMProviderError) as error:
            await provider.generate_text(messages=[LLMMessage(role="user", content="Analyze")])
    assert error.value.code == code
    assert "secret" not in error.value.safe_message


def test_service_builds_new_providers_without_changing_existing_configuration():
    settings = SimpleNamespace(
        gemini_api_key=None, gemini_model=None, groq_api_key=None, groq_model=None,
        openai_api_key=SecretStr("openai-key"), openai_model="gpt-test",
        anthropic_api_key=SecretStr("anthropic-key"), anthropic_model="claude-test",
        anthropic_max_tokens=6000, llm_request_timeout_seconds=15,
    )
    service = LLMService(settings=settings)
    assert isinstance(service._get_provider("openai"), OpenAIProvider)
    anthropic = service._get_provider("anthropic")
    assert isinstance(anthropic, AnthropicProvider)
    assert anthropic.max_tokens == 6000
