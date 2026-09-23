import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import AnalysisRunStatus, LLMProvider, MAX_QUERY_LENGTH
from app.core.exceptions import (
    AnalysisRunNotFoundError,
    AnalysisRunNotExecutableError,
    DuplicateAnalysisRunError,
    DatasetNotProfiledError,
    InvalidLLMProviderError,
    InsufficientCreditsError,
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
from app.repositories.user_repository import UserRepository
from app.services.conversation_service import ConversationService
from app.services.message_service import MessageService
from app.services.llm_settings_service import LLMSettingsService

logger = logging.getLogger(__name__)


class AnalysisRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runs = AnalysisRunRepository(session)
        self.profiles = DatasetProfileRepository(session)
        self.conversations = ConversationRepository(session)
        self.conversation_service = ConversationService(session)
        self.message_service = MessageService(session)
        self.llm_settings = LLMSettingsService(session)
        self.users = UserRepository(session)

    async def create_pending_run(
        self, conversation_id: UUID, query: str, llm_provider: str | None, user: User, *, force: bool = False,
    ) -> tuple[Message, AnalysisRun]:
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        normalized_query = self._normalize_query(query)
        # Legacy clients may still submit a provider; only the saved admin setting controls it.
        provider = self._normalize_provider(await self.llm_settings.selected_provider())
        profile = await self.profiles.get_by_dataset_id(conversation.dataset_id)
        if profile is None or profile.profile_status != DatasetProfileStatus.COMPLETED.value:
            raise DatasetNotProfiledError
        if not force:
            duplicate = await self.runs.find_duplicate(
                dataset_id=conversation.dataset_id,
                user_id=user.id,
                normalized_query=normalized_query,
            )
            if duplicate is not None:
                raise DuplicateAnalysisRunError(duplicate.id, duplicate.status)

        # Lock the balance while reserving capacity for this pending run. The
        # balance itself is only reduced when the answer is completed.
        locked_user = await self.users.get_by_id_for_update(user.id)
        active_reservations = await self.runs.count_active_for_user(user.id)
        if locked_user is None or locked_user.credits <= active_reservations:
            raise InsufficientCreditsError
        user.credits = locked_user.credits

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

    async def retry_run(self, analysis_run_id: UUID, user: User, provider: str | None = None) -> tuple[Message, AnalysisRun]:
        original = await self.get_run(analysis_run_id, user)
        if original.status not in {AnalysisRunStatus.FAILED.value, AnalysisRunStatus.CANCELLED.value}:
            raise AnalysisRunNotExecutableError
        return await self.create_pending_run(
            original.conversation_id,
            original.query,
            None,
            user,
            force=True,
        )

    async def cancel_run(self, analysis_run_id: UUID, user: User) -> AnalysisRun:
        run = await self.get_run(analysis_run_id, user)
        if run.status not in {AnalysisRunStatus.PENDING.value, AnalysisRunStatus.RUNNING.value}:
            raise AnalysisRunNotExecutableError
        await self.runs.cancel(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def queue_position(self, analysis_run_id: UUID, user: User) -> tuple[AnalysisRun, int | None]:
        run = await self.get_run(analysis_run_id, user)
        return run, await self.runs.queue_position(run)

    async def get_run(self, analysis_run_id: UUID, user: User) -> AnalysisRun:
        analysis_run = await self.runs.get_by_id_for_user(analysis_run_id, user.id)
        if analysis_run is None:
            raise AnalysisRunNotFoundError
        return analysis_run

    async def list_runs(self, conversation_id: UUID, user: User) -> list[AnalysisRun]:
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        return await self.runs.list_for_conversation(conversation.id, user.id)

    async def list_active_runs(self, user: User) -> list[AnalysisRun]:
        return await self.runs.list_active_for_user(user.id)

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
