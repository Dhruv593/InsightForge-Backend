import json
from time import perf_counter

import httpx
from pydantic import BaseModel, ValidationError

from app.core.tracing import traced
from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.services.llm.base import BaseLLMProvider, LLMProviderError


class OpenAIProvider(BaseLLMProvider):
    provider_name = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    @traced("openai.structured", run_type="llm")
    async def generate_structured(self, *, messages: list[LLMMessage], response_model: type[BaseModel]) -> LLMResult:
        payload = {
            "model": self.model_name,
            "input": [message.model_dump() for message in messages],
            "text": {"format": {
                "type": "json_schema",
                "name": response_model.__name__.lower()[:64],
                "schema": response_model.model_json_schema(),
                "strict": False,
            }},
            "store": False,
        }
        started = perf_counter()
        data = await self._request(payload)
        try:
            text = self._output_text(data)
            validated = response_model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "The selected LLM provider returned an invalid structured response.",
            ) from exc
        return self._result(data, validated.model_dump(mode="json"), started)

    @traced("openai.text", run_type="llm")
    async def generate_text(self, *, messages: list[LLMMessage]) -> LLMResult:
        started = perf_counter()
        data = await self._request({
            "model": self.model_name,
            "input": [message.model_dump() for message in messages],
            "store": False,
        })
        try:
            text = self._output_text(data)
        except (ValueError, TypeError) as exc:
            raise LLMProviderError("LLM_INVALID_RESPONSE", "The selected LLM provider returned an invalid response.") from exc
        return self._result(data, {"text": text}, started)

    async def _request(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
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
        for item in data.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") == "output_text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        return text
        raise ValueError("OpenAI response did not contain output text.")

    def _result(self, data: dict[str, object], content: dict[str, object], started: float) -> LLMResult:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMResult(
            provider="openai",
            model=self.model_name,
            content=content,
            usage=LLMUsage(
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
            ),
            latency_ms=round((perf_counter() - started) * 1000),
        )
