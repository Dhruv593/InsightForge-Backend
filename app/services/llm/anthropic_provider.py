import json
from time import perf_counter

import httpx
from pydantic import BaseModel, ValidationError

from app.core.tracing import traced
from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.services.llm.base import BaseLLMProvider, LLMProviderError


class AnthropicProvider(BaseLLMProvider):
    provider_name = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: int, max_tokens: int = 8192) -> None:
        super().__init__(api_key=api_key, model=model, timeout_seconds=timeout_seconds)
        self.max_tokens = max_tokens

    @traced("anthropic.structured", run_type="llm")
    async def generate_structured(self, *, messages: list[LLMMessage], response_model: type[BaseModel]) -> LLMResult:
        payload = self._payload(messages)
        payload["output_config"] = {"format": {
            "type": "json_schema",
            "schema": response_model.model_json_schema(),
        }}
        started = perf_counter()
        data = await self._request(payload)
        try:
            validated = response_model.model_validate(json.loads(self._output_text(data)))
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "The selected LLM provider returned an invalid structured response.",
            ) from exc
        return self._result(data, validated.model_dump(mode="json"), started)

    @traced("anthropic.text", run_type="llm")
    async def generate_text(self, *, messages: list[LLMMessage]) -> LLMResult:
        started = perf_counter()
        data = await self._request(self._payload(messages))
        try:
            text = self._output_text(data)
        except (ValueError, TypeError) as exc:
            raise LLMProviderError("LLM_INVALID_RESPONSE", "The selected LLM provider returned an invalid response.") from exc
        return self._result(data, {"text": text}, started)

    def _payload(self, messages: list[LLMMessage]) -> dict[str, object]:
        system = "\n\n".join(message.content for message in messages if message.role == "system").strip()
        payload: dict[str, object] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "messages": [message.model_dump() for message in messages if message.role != "system"],
        }
        if system:
            payload["system"] = system
        return payload

    async def _request(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            self._raise_for_status(response)
            return response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM_TIMEOUT", "The LLM request timed out.") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("LLM_PROVIDER_UNAVAILABLE", "The selected LLM provider is temporarily unavailable.") from exc
        except LLMProviderError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise LLMProviderError("LLM_INVALID_RESPONSE", "The selected LLM provider returned an invalid response.") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in {401, 403}:
            raise LLMProviderError("LLM_AUTHENTICATION_FAILED", "The selected LLM provider could not authenticate the request.")
        if response.status_code == 429:
            raise LLMProviderError("LLM_RATE_LIMITED", "The selected LLM provider is temporarily rate limited.")
        if response.status_code >= 500:
            raise LLMProviderError("LLM_PROVIDER_UNAVAILABLE", "The selected LLM provider is temporarily unavailable.")
        raise LLMProviderError("LLM_EXECUTION_FAILED", "The selected LLM provider could not complete the request.")

    @staticmethod
    def _output_text(data: dict[str, object]) -> str:
        for block in data.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    return text
        raise ValueError("Anthropic response did not contain text.")

    def _result(self, data: dict[str, object], content: dict[str, object], started: float) -> LLMResult:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("output_tokens")
        total_tokens = prompt_tokens + completion_tokens if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int) else None
        return LLMResult(
            provider="anthropic",
            model=self.model_name,
            content=content,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            latency_ms=round((perf_counter() - started) * 1000),
        )
