import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.user import User
from app.repositories.llm_settings_repository import LLMSettingsRepository
from app.schemas.llm_settings import LLMProviderOption, LLMSettingsResponse, LLMSettingsUpdate

logger = logging.getLogger(__name__)


class LLMSettingsService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repository = LLMSettingsRepository(session)

    def options(self) -> list[LLMProviderOption]:
        options = []
        for provider, label in (
            ("gemini", "Google Gemini"),
            ("groq", "Groq"),
            ("openai", "OpenAI (ChatGPT)"),
            ("anthropic", "Anthropic Claude"),
        ):
            key = getattr(self.settings, f"{provider}_api_key")
            model = (getattr(self.settings, f"{provider}_model") or "").strip()
            options.append(LLMProviderOption(
                provider=provider, label=label, model=model or None,
                configured=bool(key and key.get_secret_value().strip() and model),
            ))
        return options

    async def selected_provider(self) -> str:
        entry = await self.repository.get()
        return entry.provider if entry else self.settings.default_llm_provider

    async def get(self) -> LLMSettingsResponse:
        entry = await self.repository.get()
        return LLMSettingsResponse(
            provider=entry.provider if entry else self.settings.default_llm_provider,
            options=self.options(), updated_at=entry.updated_at if entry else None,
        )

    async def update(self, payload: LLMSettingsUpdate, user: User) -> LLMSettingsResponse:
        if not user.is_admin:
            raise AppError("ADMIN_ACCESS_REQUIRED", "Owner access is required.", 403)
        option = next(item for item in self.options() if item.provider == payload.provider)
        if not option.configured:
            raise AppError("LLM_PROVIDER_NOT_CONFIGURED", "Configure this provider's API key and model on the server before selecting it.", 422)
        try:
            entry = await self.repository.set_provider(payload.provider, user.id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        logger.info("System LLM provider updated provider=%s admin_id=%s", payload.provider, user.id)
        return LLMSettingsResponse(provider=entry.provider, options=self.options(), updated_at=entry.updated_at)
