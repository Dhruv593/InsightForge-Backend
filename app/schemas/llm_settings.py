from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ProviderName = Literal["gemini", "groq"]


class LLMSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName


class LLMProviderOption(BaseModel):
    provider: ProviderName
    label: str
    model: str | None
    configured: bool


class LLMSettingsResponse(BaseModel):
    provider: ProviderName
    options: list[LLMProviderOption]
    updated_at: datetime | None = None
