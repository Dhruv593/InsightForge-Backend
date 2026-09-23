from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, InvalidCredentialsError
from app.core.security import hash_password, verify_password
from app.email_templates import (
    RenderedEmail,
    account_deleted_email,
    email_verification_email,
    password_changed_email,
    password_reset_email,
)
from app.models.user import User
from app.repositories.dataset_repository import DatasetRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.account_token_repository import AccountTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.cloudinary_service import CloudinaryDeleteError, CloudinaryService
from app.services.email_service import EmailDeliveryUnavailable, EmailService
from app.services.site_content_service import SiteContentService
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = SessionRepository(session)
        self.datasets = DatasetRepository(session)
        self.cloudinary = CloudinaryService()
        self.tokens = AccountTokenRepository(session)
        self.users = UserRepository(session)
        self.email = EmailService()
        self.content = SiteContentService(session)

    async def update_profile(self, user: User, name: str) -> User:
        user.name = name.strip()
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def complete_onboarding(self, user: User) -> User:
        if user.onboarding_completed_at is None:
            user.onboarding_completed_at = datetime.now(timezone.utc)
            await self.session.commit()
            await self.session.refresh(user)
        return user

    async def change_password(self, user: User, current_password: str | None, new_password: str) -> None:
        if user.password_hash and (not current_password or not verify_password(current_password, user.password_hash)):
            raise InvalidCredentialsError
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        await self.sessions.revoke_all_for_user(user.id)
        await self.session.commit()
        settings = get_settings()
        templates = await self.content.resolve_email_templates()
        email = password_changed_email(
            user_name=user.name,
            changed_at=datetime.now(timezone.utc),
            frontend_url=settings.frontend_url,
            support_email=self._support_email(),
            template=templates.password_changed,
        )
        await self._send_best_effort(user.email, email, "password change", user.id)

    async def list_sessions(self, user: User):
        return await self.sessions.list_for_user(user.id)

    async def revoke_session(self, user: User, session_id: UUID) -> None:
        if not await self.sessions.revoke_by_id_for_user(session_id, user.id):
            raise AppError("SESSION_NOT_FOUND", "Session not found or already signed out.", 404)
        await self.session.commit()

    async def revoke_all_sessions(self, user: User) -> None:
        await self.sessions.revoke_all_for_user(user.id)
        user.token_version += 1
        await self.session.commit()

    async def delete_account(self, user: User, password: str | None, confirmation: str) -> None:
        if confirmation.strip().upper() != "DELETE":
            raise AppError("ACCOUNT_DELETE_CONFIRMATION_REQUIRED", "Enter DELETE to confirm account deletion.", 422)
        if user.password_hash and (not password or not verify_password(password, user.password_hash)):
            raise InvalidCredentialsError
        user_id = user.id
        user_name = user.name
        recipient = user.email
        for dataset in await self.datasets.list_for_user(user.id):
            try:
                await self.cloudinary.delete_dataset_file(
                    public_id=dataset.cloudinary_public_id,
                    resource_type=dataset.cloudinary_resource_type,
                    user_id=user.id,
                    dataset_id=dataset.id,
                    delivery_type="authenticated" if "/raw/authenticated/" in dataset.cloudinary_url else "upload",
                )
            except CloudinaryDeleteError as exc:
                raise AppError("ACCOUNT_DATA_DELETE_FAILED", "Stored dataset files could not be deleted. Please try again.", 502) from exc
        await self.session.delete(user)
        await self.session.commit()
        settings = get_settings()
        templates = await self.content.resolve_email_templates()
        email = account_deleted_email(
            user_name=user_name,
            deleted_at=datetime.now(timezone.utc),
            frontend_url=settings.frontend_url,
            support_email=self._support_email(),
            template=templates.account_deleted,
        )
        await self._send_best_effort(recipient, email, "account deletion", user_id)

    async def send_verification(self, user: User) -> None:
        if user.is_email_verified:
            return
        if await self.tokens.created_recently(user.id, "email_verification"):
            return
        raw = await self._create_token(user.id, "email_verification", hours=24)
        settings = get_settings()
        templates = await self.content.resolve_email_templates()
        url = f"{settings.frontend_url.rstrip('/')}/verify-email?token={raw}"
        email = email_verification_email(
            user_name=user.name,
            verification_url=url,
            frontend_url=settings.frontend_url,
            support_email=self._support_email(),
            template=templates.email_verification,
        )
        try:
            await self.email.send_rendered(recipient=user.email, email=email)
        except EmailDeliveryUnavailable as exc:
            raise AppError("EMAIL_DELIVERY_NOT_CONFIGURED", "Email delivery is not configured yet.", 503) from exc

    async def verify_email(self, raw_token: str) -> None:
        token = await self.tokens.consume(self._hash_token(raw_token), "email_verification")
        if token is None:
            raise AppError("VERIFICATION_TOKEN_INVALID", "This verification link is invalid or expired.", 422)
        user = await self.users.get_by_id(token.user_id)
        if user is None:
            raise AppError("VERIFICATION_TOKEN_INVALID", "This verification link is invalid or expired.", 422)
        user.is_email_verified = True
        await self.session.commit()

    async def request_password_reset(self, email: str) -> None:
        user = await self.users.get_by_email(email.strip().lower())
        if user is None or not user.is_active:
            return
        if await self.tokens.created_recently(user.id, "password_reset"):
            return
        raw = await self._create_token(user.id, "password_reset", hours=1)
        settings = get_settings()
        templates = await self.content.resolve_email_templates()
        url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw}"
        email = password_reset_email(
            user_name=user.name,
            reset_url=url,
            frontend_url=settings.frontend_url,
            support_email=self._support_email(),
            template=templates.password_reset,
        )
        try:
            await self.email.send_rendered(recipient=user.email, email=email)
        except Exception:
            logger.exception("Password reset email could not be delivered user_id=%s", user.id)

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        token = await self.tokens.consume(self._hash_token(raw_token), "password_reset")
        if token is None:
            raise AppError("PASSWORD_RESET_TOKEN_INVALID", "This password reset link is invalid or expired.", 422)
        user = await self.users.get_by_id(token.user_id)
        if user is None:
            raise AppError("PASSWORD_RESET_TOKEN_INVALID", "This password reset link is invalid or expired.", 422)
        user.password_hash = hash_password(new_password)
        user.token_version += 1
        await self.sessions.revoke_all_for_user(user.id)
        await self.session.commit()
        settings = get_settings()
        templates = await self.content.resolve_email_templates()
        email = password_changed_email(
            user_name=user.name,
            changed_at=datetime.now(timezone.utc),
            frontend_url=settings.frontend_url,
            support_email=self._support_email(),
            template=templates.password_changed,
        )
        await self._send_best_effort(user.email, email, "password reset confirmation", user.id)

    async def _create_token(self, user_id: UUID, token_type: str, *, hours: int) -> str:
        raw = secrets.token_urlsafe(32)
        await self.tokens.create(user_id=user_id, token_type=token_type, token_hash=self._hash_token(raw), expires_at=datetime.now(timezone.utc) + timedelta(hours=hours))
        await self.session.commit()
        return raw

    @staticmethod
    def _hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _support_email() -> str:
        settings = get_settings()
        return settings.support_email.strip() or settings.smtp_from_email.strip()

    async def _send_best_effort(self, recipient: str, email: RenderedEmail, event: str, user_id: UUID) -> None:
        try:
            await self.email.send_rendered(recipient=recipient, email=email)
        except Exception:
            logger.exception("%s email could not be delivered user_id=%s", event.capitalize(), user_id)
