from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import MessageRole, MessageType
from app.models.analysis_run import AnalysisRun
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.repositories.message_repository import MessageRepository
from app.services.conversation_service import ConversationService


class MessageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.messages = MessageRepository(session)
        self.conversation_service = ConversationService(session)

    async def create_user_message(
        self, conversation: Conversation, content: str, analysis_run: AnalysisRun
    ) -> Message:
        return await self.messages.create(
            Message(
                conversation_id=conversation.id,
                analysis_run_id=analysis_run.id,
                role=MessageRole.USER.value,
                content=content,
                message_type=MessageType.TEXT.value,
            )
        )

    async def list_messages(self, conversation_id: UUID, user: User) -> list[Message]:
        conversation = await self.conversation_service.get_conversation(conversation_id, user)
        return await self.messages.list_for_conversation(conversation.id)

    async def create_assistant_message(
        self, conversation_id: UUID, analysis_run: AnalysisRun, content: str
    ) -> Message:
        """Create the persisted assistant result for a completed analysis run."""
        return await self.messages.create(
            Message(
                conversation_id=conversation_id,
                analysis_run_id=analysis_run.id,
                role=MessageRole.ASSISTANT.value,
                content=content,
                message_type=MessageType.ANALYSIS_RESULT.value,
            )
        )
