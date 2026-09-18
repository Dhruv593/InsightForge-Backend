from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_entry import ContentEntry


class ContentEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, content_type: str, slug: str) -> ContentEntry | None:
        result = await self.session.execute(
            select(ContentEntry).where(
                ContentEntry.content_type == content_type,
                ContentEntry.slug == slug,
            )
        )
        return result.scalar_one_or_none()

    async def get_published(self, content_type: str, slug: str) -> ContentEntry | None:
        result = await self.session.execute(
            select(ContentEntry).where(
                ContentEntry.content_type == content_type,
                ContentEntry.slug == slug,
                ContentEntry.status == "published",
            )
        )
        return result.scalar_one_or_none()

    async def save(self, entry: ContentEntry) -> ContentEntry:
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list(self, content_type: str, *, published_only: bool) -> list[ContentEntry]:
        query = select(ContentEntry).where(ContentEntry.content_type == content_type)
        if published_only:
            query = query.where(ContentEntry.status == "published")
        result = await self.session.execute(query.order_by(ContentEntry.updated_at.desc()))
        return list(result.scalars().all())

    async def delete(self, entry: ContentEntry) -> None:
        await self.session.delete(entry)
        await self.session.flush()
