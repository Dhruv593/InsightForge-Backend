from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMResult(BaseModel):
    provider: Literal["gemini", "groq", "openai", "anthropic"]
    model: str
    content: dict[str, Any]
    usage: LLMUsage
    latency_ms: int


class PipelineTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    status: Literal["success"]
