from typing import Annotated
import logging

from fastapi import APIRouter, Depends, status

from app.api.dependencies import CurrentUser, get_auth_service
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    LogoutResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService, IssuedTokens
from app.services.account_service import AccountService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    user, tokens = await auth_service.register_user(
        name=payload.name,
        email=str(payload.email),
        password=payload.password,
    )
    try:
        await AccountService(auth_service.session).send_verification(user)
    except Exception:
        logger.exception("Initial verification email could not be prepared user_id=%s", user.id)
    return AuthResponse(user=UserResponse.model_validate(user), **_token_response(tokens).model_dump())


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthResponse:
    user, tokens = await auth_service.authenticate_user(
        email=str(payload.email),
        password=payload.password,
    )
    return AuthResponse(user=UserResponse.model_validate(user), **_token_response(tokens).model_dump())


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return _token_response(
        await auth_service.refresh_session(payload.refresh_token),
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    await auth_service.logout(payload.refresh_token)
    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def current_user(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
