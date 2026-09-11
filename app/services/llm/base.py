from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from app.schemas.llm import LLMMessage, LLMResult


class LLMProviderError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class BaseLLMProvider(ABC):
    provider_name: ClassVar[str]

    def __init__(self, *, api_key: str, model: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.model_name = model
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def generate_structured(
        self,
        *,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
    ) -> LLMResult:
        raise NotImplementedError

    async def generate_text(self, *, messages: list[LLMMessage]) -> LLMResult:
        raise NotImplementedError
