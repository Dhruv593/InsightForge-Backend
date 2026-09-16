from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_token import AccountToken


class AccountTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: UUID, token_type: str, token_hash: str, expires_at: datetime) -> AccountToken:
        await self.session.execute(
            update(AccountToken).where(AccountToken.user_id == user_id, AccountToken.token_type == token_type, AccountToken.used_at.is_(None)).values(used_at=datetime.now(timezone.utc))
        )
        token = AccountToken(user_id=user_id, token_type=token_type, token_hash=token_hash, expires_at=expires_at)
        self.session.add(token)
        await self.session.flush()
        return token

    async def consume(self, token_hash: str, token_type: str) -> AccountToken | None:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(AccountToken).where(AccountToken.token_hash == token_hash, AccountToken.token_type == token_type, AccountToken.used_at.is_(None), AccountToken.expires_at > now).with_for_update()
        )
        token = result.scalar_one_or_none()
        if token:
            token.used_at = now
            await self.session.flush()
        return token

    async def created_recently(self, user_id: UUID, token_type: str, seconds: int = 60) -> bool:
        result = await self.session.execute(
            select(AccountToken.id).where(
                AccountToken.user_id == user_id,
                AccountToken.token_type == token_type,
                AccountToken.created_at > datetime.now(timezone.utc) - timedelta(seconds=seconds),
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None
