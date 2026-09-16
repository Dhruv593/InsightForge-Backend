from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.db.session import get_db_session
from app.schemas.auth import AccountDeleteRequest, ForgotPasswordRequest, LogoutResponse, PasswordChangeRequest, ProfileUpdateRequest, ResetPasswordRequest, SessionListResponse, SessionResponse, UserResponse, VerifyEmailRequest
from app.services.account_service import AccountService

router = APIRouter(prefix="/account", tags=["account"])


def service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AccountService:
    return AccountService(session)


@router.post("/forgot-password", response_model=LogoutResponse)
async def forgot_password(payload: ForgotPasswordRequest, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.request_password_reset(str(payload.email))
    return LogoutResponse()


@router.post("/reset-password", response_model=LogoutResponse)
async def reset_password(payload: ResetPasswordRequest, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.reset_password(payload.token, payload.new_password)
    return LogoutResponse()


@router.post("/verify-email", response_model=LogoutResponse)
async def verify_email(payload: VerifyEmailRequest, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.verify_email(payload.token)
    return LogoutResponse()


@router.post("/verification-email", response_model=LogoutResponse)
async def resend_verification(user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.send_verification(user)
    return LogoutResponse()


@router.patch("/profile", response_model=UserResponse)
async def update_profile(payload: ProfileUpdateRequest, user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> UserResponse:
    return UserResponse.model_validate(await account.update_profile(user, payload.name))


@router.post("/password", response_model=LogoutResponse)
async def change_password(payload: PasswordChangeRequest, user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.change_password(user, payload.current_password, payload.new_password)
    return LogoutResponse()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> SessionListResponse:
    items = await account.list_sessions(user)
    return SessionListResponse(items=[SessionResponse.model_validate(item) for item in items], total=len(items))


@router.delete("/sessions/{session_id}", response_model=LogoutResponse)
async def revoke_session(session_id: UUID, user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.revoke_session(user, session_id)
    return LogoutResponse()


@router.delete("/sessions", response_model=LogoutResponse)
async def revoke_all_sessions(user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.revoke_all_sessions(user)
    return LogoutResponse()


@router.post("/delete", response_model=LogoutResponse)
async def delete_account(payload: AccountDeleteRequest, user: CurrentUser, account: Annotated[AccountService, Depends(service)]) -> LogoutResponse:
    await account.delete_account(user, payload.password, payload.confirmation)
    return LogoutResponse()
