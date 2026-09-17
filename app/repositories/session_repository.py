from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_session import UserSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> UserSession:
        user_session = UserSession(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
        )
        self.session.add(user_session)
        await self.session.flush()
        return user_session

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession).where(
                UserSession.refresh_token_hash == token_hash,
            ),
        )
        return result.scalar_one_or_none()

    async def is_active(self, session_id: UUID, user_id: UUID) -> bool:
        result = await self.session.scalar(select(UserSession.id).where(
            UserSession.id == session_id, UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(timezone.utc),
        ))
        return result is not None

    async def get_active_by_token_hash_for_update(
        self,
        token_hash: str,
    ) -> UserSession | None:
        result = await self.session.execute(
            select(UserSession)
            .where(
                UserSession.refresh_token_hash == token_hash,
                UserSession.revoked_at.is_(None),
            )
            .with_for_update(),
        )
        return result.scalar_one_or_none()

    async def revoke(self, user_session: UserSession) -> None:
        if user_session.revoked_at is None:
            user_session.revoked_at = datetime.now(timezone.utc)
            await self.session.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        await self.session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc)),
        )

    async def list_for_user(self, user_id: UUID) -> list[UserSession]:
        result = await self.session.execute(
            select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_by_id_for_user(self, session_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return bool(result.rowcount)
