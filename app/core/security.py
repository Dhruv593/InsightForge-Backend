import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError as JWTInvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

password_hash = PasswordHash.recommended()


class TokenDecodeError(Exception):
    """Raised when a JWT is invalid, expired, or has the wrong token type."""


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_password: str) -> bool:
    return password_hash.verify(password, encoded_password)


def _create_token(
    user_id: UUID,
    token_type: TokenType,
    expires_at: datetime,
    *,
    token_id: UUID | None = None,
    token_version: int | None = None,
    session_id: UUID | None = None,
) -> str:
    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type,
        "iat": issued_at,
        "exp": expires_at,
    }
    if token_id is not None:
        payload["jti"] = str(token_id)
    if token_version is not None:
        payload["ver"] = token_version
    if session_id is not None:
        payload["sid"] = str(session_id)

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user_id: UUID, token_version: int = 0, session_id: UUID | None = None) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes,
    )
    return _create_token(user_id, "access", expires_at, token_version=token_version, session_id=session_id)


def create_refresh_token(
    user_id: UUID,
    expires_at: datetime | None = None,
) -> str:
    settings = get_settings()
    token_expiry = expires_at or (
        datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days)
    )
    return _create_token(
        user_id,
        "refresh",
        token_expiry,
        token_id=uuid4(),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "type", "iat", "exp"]},
        )
    except JWTInvalidTokenError as exc:
        raise TokenDecodeError from exc

    if payload.get("type") != expected_type:
        raise TokenDecodeError
    if expected_type == "refresh" and not payload.get("jti"):
        raise TokenDecodeError

    return payload


def hash_refresh_token(token: str) -> str:
    secret = get_settings().jwt_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
