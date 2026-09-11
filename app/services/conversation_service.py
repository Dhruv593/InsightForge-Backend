import logging
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import (
    DEFAULT_CONVERSATION_TITLE,
    MAX_CONVERSATION_TITLE_LENGTH,
)
from app.core.exceptions import (
    ConversationNotFoundError,
    DatasetNotFoundError,
    InvalidConversationTitleError,
)
from app.models.conversation import Conversation
from app.models.user import User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.dataset_repository import DatasetRepository

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.datasets = DatasetRepository(session)

    async def create_conversation(
        self, dataset_id: UUID, title: str | None, user: User
    ) -> Conversation:
        dataset = await self.datasets.get_for_user(dataset_id=dataset_id, user_id=user.id)
        if dataset is None:
            raise DatasetNotFoundError
        normalized_title = self._normalize_title(title, allow_default=True)
        conversation = Conversation(
            user_id=user.id, dataset_id=dataset.id, title=normalized_title
        )
        try:
            await self.conversations.create(conversation)
            await self.session.commit()
            await self.session.refresh(conversation)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info(
            "Conversation created user_id=%s conversation_id=%s dataset_id=%s",
            user.id, conversation.id, dataset.id,
        )
        return conversation

    async def get_conversation(self, conversation_id: UUID, user: User) -> Conversation:
        conversation = await self.conversations.get_by_id_for_user(conversation_id, user.id)
        if conversation is None:
            raise ConversationNotFoundError
        return conversation

    async def list_conversations(
        self, user: User, dataset_id: UUID | None = None
    ) -> list[Conversation]:
        if dataset_id is not None:
            dataset = await self.datasets.get_for_user(dataset_id=dataset_id, user_id=user.id)
            if dataset is None:
                raise DatasetNotFoundError
        return await self.conversations.list_for_user(user.id, dataset_id)

    async def update_conversation(
        self, conversation_id: UUID, title: str, user: User
    ) -> Conversation:
        conversation = await self.get_conversation(conversation_id, user)
        normalized_title = self._normalize_title(title, allow_default=False)
        try:
            await self.conversations.update_title(conversation, normalized_title)
            await self.session.commit()
            await self.session.refresh(conversation)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info(
            "Conversation updated user_id=%s conversation_id=%s dataset_id=%s",
            user.id, conversation.id, conversation.dataset_id,
        )
        return conversation

    async def delete_conversation(self, conversation_id: UUID, user: User) -> None:
        conversation = await self.get_conversation(conversation_id, user)
        dataset_id = conversation.dataset_id
        try:
            await self.conversations.delete(conversation)
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info(
            "Conversation deleted user_id=%s conversation_id=%s dataset_id=%s",
            user.id, conversation_id, dataset_id,
        )

    @staticmethod
    def _normalize_title(title: str | None, *, allow_default: bool) -> str:
        if title is None and allow_default:
            return DEFAULT_CONVERSATION_TITLE
        normalized = (title or "").strip()
        if not normalized or len(normalized) > MAX_CONVERSATION_TITLE_LENGTH:
            raise InvalidConversationTitleError
        return normalized
