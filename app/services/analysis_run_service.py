import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import AnalysisRunStatus, LLMProvider, MAX_QUERY_LENGTH
from app.core.exceptions import (
    AnalysisRunNotFoundError,
    DatasetNotProfiledError,
    InvalidLLMProviderError,
    MessageEmptyError,
    QueryTooLongError,
)
from app.models.analysis_run import AnalysisRun
from app.models.dataset_profile import DatasetProfileStatus
from app.models.message import Message
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.dataset_profile_repository import DatasetProfileRepository
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService

logger = logging.getLogger(__name__)


class AnalysisRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runs = AnalysisRunRepository(session)
        self.profiles = DatasetProfileRepository(session)
        self.conversations = ConversationRepository(session)
        self.conversation_service = ConversationService(session)
        self.message_service = MessageService(session)

    async def create_pending_run(
        self, conversation_id: UUID, query: str, llm_provider: str, user: User
    ) -> tuple[Message, AnalysisRun]:
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        normalized_query = self._normalize_query(query)
        provider = self._normalize_provider(llm_provider)
        profile = await self.profiles.get_by_dataset_id(conversation.dataset_id)
        if profile is None or profile.profile_status != DatasetProfileStatus.COMPLETED.value:
            raise DatasetNotProfiledError

        analysis_run = AnalysisRun(
            user_id=user.id,
            dataset_id=conversation.dataset_id,
            conversation_id=conversation.id,
            query=normalized_query,
            llm_provider=provider,
            status=AnalysisRunStatus.PENDING.value,
        )
        try:
            await self.runs.create(analysis_run)
            message = await self.message_service.create_user_message(
                conversation, normalized_query, analysis_run
            )
            await self.conversations.touch(conversation)
            await self.session.commit()
            await self.session.refresh(analysis_run)
            await self.session.refresh(message)
        except Exception:
            await self.session.rollback()
            raise

        logger.info(
            "Analysis run queued user_id=%s conversation_id=%s dataset_id=%s analysis_run_id=%s provider=%s",
            user.id, conversation.id, conversation.dataset_id, analysis_run.id, provider,
        )
        return message, analysis_run

    async def get_run(self, analysis_run_id: UUID, user: User) -> AnalysisRun:
        analysis_run = await self.runs.get_by_id_for_user(analysis_run_id, user.id)
        if analysis_run is None:
            raise AnalysisRunNotFoundError
        return analysis_run

    async def list_runs(self, conversation_id: UUID, user: User) -> list[AnalysisRun]:
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        return await self.runs.list_for_conversation(conversation.id, user.id)

    @staticmethod
    def _normalize_query(query: str) -> str:
        normalized = query.strip()
        if not normalized:
            raise MessageEmptyError
        if len(normalized) > MAX_QUERY_LENGTH:
            raise QueryTooLongError
        return normalized

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        normalized = provider.strip().lower()
        if normalized not in {item.value for item in LLMProvider}:
            raise InvalidLLMProviderError
        return normalized
