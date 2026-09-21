from uuid import UUID

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_settings import LLMSettings


class LLMSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> LLMSettings | None:
        return await self.session.get(LLMSettings, 1)

    async def set_provider(self, provider: str, admin_id: UUID) -> LLMSettings:
        statement = insert(LLMSettings).values(id=1, provider=provider, updated_by=admin_id)
        statement = statement.on_conflict_do_update(
            index_elements=[LLMSettings.id],
            set_={"provider": provider, "updated_by": admin_id, "updated_at": func.now()},
        ).returning(LLMSettings).execution_options(populate_existing=True)
        return (await self.session.execute(statement)).scalar_one()
