import asyncio
import logging
from app.prompts.llm_recovery_prompt import STRUCTURED_RETRY_PROMPT
from app.core.tracing import trace_event

from pydantic import BaseModel

from app.core.analysis_constants import LLMProvider
from app.core.config import Settings, get_settings
from app.schemas.llm import LLMMessage, LLMResult
from app.services.llm.base import BaseLLMProvider, LLMProviderError
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.anthropic_provider import AnthropicProvider

logger = logging.getLogger(__name__)
RETRYABLE_CODES = {"LLM_INVALID_RESPONSE", "LLM_TIMEOUT", "LLM_RATE_LIMITED", "LLM_PROVIDER_UNAVAILABLE", "LLM_EXECUTION_FAILED"}


class LLMService:
    def __init__(
        self,
        settings: Settings | None = None,
        providers: dict[str, BaseLLMProvider] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._providers = providers or {}

    async def generate_structured(
        self,
        *,
        provider: str,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
    ) -> LLMResult:
        selected = self._get_provider(provider)
        return await self._generate_with_recovery(selected, messages, response_model)

    async def generate_text(
        self,
        *,
        provider: str,
        messages: list[LLMMessage],
    ) -> LLMResult:
        return await self._generate_with_recovery(self._get_provider(provider), messages)

    async def _generate_with_recovery(self, selected, messages, response_model=None):
        # Retry only provider calls, never database writes or analytical operations.
        request_messages = list(messages)
        for attempt in range(2):
            await trace_event("provider_attempt", attempt=attempt + 1)
            try:
                if response_model is not None:
                    return await selected.generate_structured(messages=request_messages, response_model=response_model)
                return await selected.generate_text(messages=request_messages)
            except LLMProviderError as exc:
                await trace_event("provider_attempt_failed", error_code=exc.code, attempt=attempt + 1)
                if attempt or exc.code not in RETRYABLE_CODES:
                    raise
                logger.warning("Retrying LLM response provider=%s error_code=%s attempt=2", selected.provider_name, exc.code)
                if exc.code == "LLM_INVALID_RESPONSE" and response_model is not None:
                    request_messages.append(LLMMessage(role="user", content=STRUCTURED_RETRY_PROMPT))
                await asyncio.sleep(0.5)

    def model_name(self, provider: str) -> str:
        return self._get_provider(provider).model_name

    def _get_provider(self, provider: str) -> BaseLLMProvider:
        if provider not in {item.value for item in LLMProvider}:
            raise LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The selected LLM provider is not supported.",
            )
        if provider not in self._providers:
            self._providers[provider] = self._build_provider(provider)
        return self._providers[provider]

    def _build_provider(self, provider: str) -> BaseLLMProvider:
        if provider == LLMProvider.GEMINI.value:
            key = self.settings.gemini_api_key
            model = self.settings.gemini_model
            provider_class = GeminiProvider
        elif provider == LLMProvider.GROQ.value:
            key = self.settings.groq_api_key
            model = self.settings.groq_model
            provider_class = GroqProvider
        elif provider == LLMProvider.OPENAI.value:
            key = self.settings.openai_api_key
            model = self.settings.openai_model
            provider_class = OpenAIProvider
        elif provider == LLMProvider.ANTHROPIC.value:
            key = self.settings.anthropic_api_key
            model = self.settings.anthropic_model
            provider_class = AnthropicProvider
        else:
            raise LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The selected LLM provider is not supported.",
            )

        api_key = key.get_secret_value().strip() if key else ""
        model_name = model.strip() if model else ""
        if not api_key or not model_name:
            raise LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The selected LLM provider is not configured.",
            )
        provider_options = dict(
            api_key=api_key,
            model=model_name,
            timeout_seconds=self.settings.llm_request_timeout_seconds,
        )
        if provider == LLMProvider.ANTHROPIC.value:
            provider_options["max_tokens"] = self.settings.anthropic_max_tokens
        return provider_class(**provider_options)
