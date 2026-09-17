from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    DuplicateEmailError,
    InactiveUserError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.core.security import (
    TokenType,
    TokenDecodeError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = SessionRepository(session)

    async def register_user(
        self,
        *,
        name: str,
        email: str,
        password: str,
    ) -> tuple[User, IssuedTokens]:
        normalized_email = email.strip().lower()
        if await self.users.get_by_email(normalized_email) is not None:
            raise DuplicateEmailError

        try:
            user = await self.users.create(
                name=name.strip(),
                email=normalized_email,
                password_hash=hash_password(password),
            )
            tokens = await self._issue_tokens(user.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateEmailError from exc

        return user, tokens

    async def authenticate_user(
        self,
        *,
        email: str,
        password: str,
    ) -> tuple[User, IssuedTokens]:
        user = await self.users.get_by_email(email.strip().lower())
        if user is None or not user.password_hash or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError
        if not user.is_active:
            raise InactiveUserError

        tokens = await self._issue_tokens(user.id)
        await self.session.commit()
        return user, tokens

    async def refresh_session(self, refresh_token: str) -> IssuedTokens:
        user_id = self._decode_user_id(refresh_token, "refresh")
        token_hash = hash_refresh_token(refresh_token)
        stored_session = await self.sessions.get_active_by_token_hash_for_update(
            token_hash,
        )
        now = datetime.now(timezone.utc)

        if (
            stored_session is None
            or stored_session.user_id != user_id
            or stored_session.expires_at <= now
        ):
            raise InvalidRefreshTokenError

        user = await self.users.get_by_id(user_id)
        if user is None:
            raise InvalidRefreshTokenError
        if not user.is_active:
            raise InactiveUserError

        await self.sessions.revoke(stored_session)
        tokens = await self._issue_tokens(user.id)
        await self.session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        stored_session = await self.sessions.get_by_token_hash(
            hash_refresh_token(refresh_token),
        )
        if stored_session is not None:
            await self.sessions.revoke(stored_session)
            await self.session.commit()

    async def get_user_from_access_token(self, access_token: str) -> User:
        try:
            payload = decode_token(access_token, "access")
            user_id = UUID(payload["sub"])
            session_id = UUID(payload["sid"])
        except (TokenDecodeError, TypeError, ValueError, KeyError) as exc:
            raise InvalidAccessTokenError from exc
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise InvalidAccessTokenError
        if payload.get("ver") != user.token_version:
            raise InvalidAccessTokenError
        if not await self.sessions.is_active(session_id, user.id):
            raise InvalidAccessTokenError
        if not user.is_active:
            raise InactiveUserError
        return user

    async def _issue_tokens(self, user_id: UUID) -> IssuedTokens:
        settings = get_settings()
        refresh_expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days,
        )
        refresh_token = create_refresh_token(user_id, refresh_expires_at)
        stored_session = await self.sessions.create(
            user_id=user_id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_expires_at,
        )
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise InvalidAccessTokenError
        return IssuedTokens(
            access_token=create_access_token(user_id, user.token_version, stored_session.id),
            refresh_token=refresh_token,
        )

    @staticmethod
    def _decode_user_id(token: str, token_type: TokenType) -> UUID:
        try:
            payload = decode_token(token, token_type)
            return UUID(payload["sub"])
        except (TokenDecodeError, TypeError, ValueError, KeyError) as exc:
            if token_type == "refresh":
                raise InvalidRefreshTokenError from exc
            raise InvalidAccessTokenError from exc
