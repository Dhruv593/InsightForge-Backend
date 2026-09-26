from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, InvalidAccessTokenError
from app.core.logging_config import update_log_context
from app.db.session import get_db_session
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.analysis_run_service import AnalysisRunService
from app.services.analysis_execution_service import AnalysisExecutionService
from app.services.conversation_service import ConversationService
from app.services.dataset_service import DatasetService
from app.services.dataset_profiling_service import DatasetProfilingService
from app.services.message_service import MessageService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthService:
    return AuthService(session)


async def get_dataset_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DatasetService:
    return DatasetService(session)


async def get_dataset_profiling_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DatasetProfilingService:
    return DatasetProfilingService(session)


async def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationService:
    return ConversationService(session)


async def get_message_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MessageService:
    return MessageService(session)


async def get_analysis_run_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnalysisRunService:
    return AnalysisRunService(session)


async def get_analysis_execution_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnalysisExecutionService:
    return AnalysisExecutionService(session)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidAccessTokenError
    user = await auth_service.get_user_from_access_token(credentials.credentials)
    update_log_context(user_id=user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin_user(user: CurrentUser) -> User:
    if not user.is_admin:
        raise AppError("ADMIN_ACCESS_REQUIRED", "Owner access is required.", 403)
    return user


AdminUser = Annotated[User, Depends(get_current_admin_user)]
