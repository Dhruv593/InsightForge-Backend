"""Google Identity Services sign-in; credentials are never logged or stored."""
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_auth_service
from app.core.config import get_settings
from app.core.exceptions import AppError, InactiveUserError
from app.models.user import User
from app.schemas.auth import AuthResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth/google", tags=["authentication"])
COOKIE = "insightforge_google_nonce"


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=16384)


def check_origin(request: Request):
    settings = get_settings()
    if not settings.google_client_id.strip():
        raise AppError("GOOGLE_NOT_CONFIGURED", "Google sign-in is not configured yet. Please use email and password.", 503)
    if request.headers.get("origin") != settings.frontend_url.rstrip("/"):
        raise AppError("GOOGLE_ORIGIN_INVALID", "Please sign in from the configured application address.", 403)
    return settings


def cookie_policy(frontend_url: str) -> dict[str, object]:
    """Allow the nonce across the separately hosted frontend and API in production."""
    secure = frontend_url.startswith("https://")
    return {"secure": secure, "samesite": "none" if secure else "lax"}


@router.post("/challenge")
async def challenge(request: Request, response: Response):
    settings = check_origin(request)
    nonce = secrets.token_urlsafe(32)
    response.set_cookie(COOKIE, nonce, max_age=300, httponly=True,
                        path=f"{settings.api_v1_prefix}/auth/google",
                        **cookie_policy(settings.frontend_url))
    response.headers["Cache-Control"] = "no-store"
    return {"nonce": nonce, "client_id": settings.google_client_id}


def verify_credential(credential, client_id):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token

    class TimedRequest(GoogleRequest):
        def __call__(self, *args, **kwargs):
            kwargs["timeout"] = 10
            return super().__call__(*args, **kwargs)

    return verify_oauth2_token(credential, TimedRequest(), client_id)


@router.post("", response_model=AuthResponse)
async def google_login(payload: GoogleLoginRequest, request: Request, response: Response,
                       service: Annotated[AuthService, Depends(get_auth_service)]):
    settings = check_origin(request)
    nonce = request.cookies.get(COOKIE)
    if not nonce:
        raise AppError("GOOGLE_SIGNIN_EXPIRED", "Google sign-in expired. Please reload this page and try again.", 401)
    try:
        claims = await run_in_threadpool(verify_credential, payload.credential, settings.google_client_id)
    except ValueError:
        raise AppError("GOOGLE_TOKEN_INVALID", "Google could not verify this sign-in. Please try again.", 401) from None
    except Exception:
        raise AppError("GOOGLE_UNAVAILABLE", "Google sign-in is temporarily unavailable. Please try again later.", 503) from None
    if (not isinstance(claims.get("nonce"), str)
            or not secrets.compare_digest(claims["nonce"], nonce)
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("sub"), str) or not 0 < len(claims["sub"]) <= 255):
        raise AppError("GOOGLE_TOKEN_INVALID", "Google could not verify this sign-in. Please reload and try again.", 401)
    try:
        email = str(TypeAdapter(EmailStr).validate_python(claims.get("email"))).lower()
    except ValueError:
        raise AppError("GOOGLE_EMAIL_INVALID", "Google did not return a valid verified email.", 401) from None
    user = (await service.session.execute(select(User).where(User.google_subject == claims["sub"]))).scalar_one_or_none()
    try:
        if user is None:
            if await service.users.get_by_email(email):
                raise AppError("GOOGLE_ACCOUNT_EXISTS", "This email already has an account. Please log in with your existing password.", 409)
            user = User(name=(str(claims.get("name") or email.split("@")[0]).strip() or "Google user")[:255],
                        email=email, google_subject=claims["sub"], password_hash=None)
            service.session.add(user)
            await service.session.flush()
        if not user.is_active:
            raise InactiveUserError
        tokens = await service._issue_tokens(user.id)
        await service.session.commit()
        await service.session.refresh(user)
    except IntegrityError:
        await service.session.rollback()
        raise AppError("GOOGLE_ACCOUNT_CONFLICT", "An account was just created for this identity. Please try signing in again.", 409) from None
    response.delete_cookie(COOKIE, path=f"{settings.api_v1_prefix}/auth/google",
                           **cookie_policy(settings.frontend_url))
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(user=UserResponse.model_validate(user), access_token=tokens.access_token, refresh_token=tokens.refresh_token)
