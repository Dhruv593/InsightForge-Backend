from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, user_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def consume_credit(self, user_id: UUID) -> int | None:
        result = await self.session.execute(
            update(User)
            .where(User.id == user_id, User.credits > 0)
            .values(credits=User.credits - 1)
            .returning(User.credits)
        )
        return result.scalar_one_or_none()

    async def adjust_credits(self, user_id: UUID, delta: int) -> int | None:
        result = await self.session.execute(
            update(User)
            .where(User.id == user_id, User.credits + delta >= 0)
            .values(credits=User.credits + delta)
            .returning(User.credits)
        )
        return result.scalar_one_or_none()

    async def list_users(self, *, search: str = "", limit: int = 100) -> tuple[list[User], int]:
        query = select(User)
        count_query = select(func.count()).select_from(User)
        normalized = search.strip().lower()
        if normalized:
            condition = func.lower(User.email).contains(normalized) | func.lower(User.name).contains(normalized)
            query = query.where(condition)
            count_query = count_query.where(condition)
        users = list((await self.session.execute(query.order_by(User.created_at.desc()).limit(limit))).scalars())
        total = int((await self.session.execute(count_query)).scalar_one())
        return users, total

    async def create(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
    ) -> User:
        user = User(name=name, email=email, password_hash=password_hash)
        self.session.add(user)
        await self.session.flush()
        return user
