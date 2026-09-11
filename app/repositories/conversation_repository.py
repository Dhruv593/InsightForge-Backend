from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.dataset import Dataset


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, conversation: Conversation) -> Conversation:
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def get_by_id_for_user(self, conversation_id: UUID, user_id: UUID) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation)
            .join(Dataset, Dataset.id == Conversation.dataset_id)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Dataset.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID, dataset_id: UUID | None = None) -> list[Conversation]:
        query = (
            select(Conversation)
            .join(Dataset, Dataset.id == Conversation.dataset_id)
            .where(Conversation.user_id == user_id, Dataset.user_id == user_id)
        )
        if dataset_id is not None:
            query = query.where(Conversation.dataset_id == dataset_id)
        result = await self.session.execute(query.order_by(Conversation.updated_at.desc()))
        return list(result.scalars().all())

    async def update_title(self, conversation: Conversation, title: str) -> Conversation:
        conversation.title = title
        await self.session.flush()
        return conversation

    async def touch(self, conversation: Conversation) -> Conversation:
        conversation.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return conversation

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()
