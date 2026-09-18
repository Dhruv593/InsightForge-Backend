import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_entry import ContentEntry
from app.models.user import User
from app.repositories.content_entry_repository import ContentEntryRepository
from app.schemas.site_content import LandingPageContent
from app.schemas.site_content import BlogContent
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

LANDING_CONTENT_TYPE = "landing_page"
LANDING_SLUG = "home"
BLOG_CONTENT_TYPE = "blog"


class SiteContentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entries = ContentEntryRepository(session)

    async def get_landing(self, *, published_only: bool) -> ContentEntry | None:
        getter = self.entries.get_published if published_only else self.entries.get
        return await getter(LANDING_CONTENT_TYPE, LANDING_SLUG)

    async def update_landing(self, content: LandingPageContent, user: User) -> ContentEntry:
        entry = await self.entries.get(LANDING_CONTENT_TYPE, LANDING_SLUG)
        if entry is None:
            entry = ContentEntry(
                content_type=LANDING_CONTENT_TYPE,
                slug=LANDING_SLUG,
                status="published",
                content=content.model_dump(mode="json"),
                updated_by=user.id,
            )
        else:
            entry.content = content.model_dump(mode="json")
            entry.status = "published"
            entry.version += 1
            entry.updated_by = user.id
        try:
            await self.entries.save(entry)
            await self.session.commit()
            await self.session.refresh(entry)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info("Landing content updated entry_id=%s version=%s admin_id=%s", entry.id, entry.version, user.id)
        return entry

    async def list_blogs(self, *, published_only: bool) -> list[ContentEntry]:
        return await self.entries.list(BLOG_CONTENT_TYPE, published_only=published_only)

    async def get_blog(self, slug: str, *, published_only: bool) -> ContentEntry:
        getter = self.entries.get_published if published_only else self.entries.get
        entry = await getter(BLOG_CONTENT_TYPE, slug)
        if entry is None:
            raise AppError("BLOG_NOT_FOUND", "Blog post not found.", 404)
        return entry

    async def save_blog(self, *, slug: str, status: str, blog: BlogContent, user: User, original_slug: str | None = None) -> ContentEntry:
        entry = await self.entries.get(BLOG_CONTENT_TYPE, original_slug or slug)
        slug_owner = await self.entries.get(BLOG_CONTENT_TYPE, slug)
        if slug_owner is not None and (entry is None or slug_owner.id != entry.id):
            raise AppError("BLOG_SLUG_EXISTS", "A blog post already uses this URL slug.", 409)
        if entry is None:
            entry = ContentEntry(content_type=BLOG_CONTENT_TYPE, slug=slug, status=status, content=blog.model_dump(mode="json"), updated_by=user.id)
        else:
            entry.slug = slug
            entry.status = status
            entry.content = blog.model_dump(mode="json")
            entry.version += 1
            entry.updated_by = user.id
        try:
            await self.entries.save(entry)
            await self.session.commit()
            await self.session.refresh(entry)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info("Blog saved entry_id=%s slug=%s status=%s admin_id=%s", entry.id, entry.slug, entry.status, user.id)
        return entry

    async def delete_blog(self, slug: str, user: User) -> None:
        entry = await self.get_blog(slug, published_only=False)
        try:
            await self.entries.delete(entry)
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info("Blog deleted entry_id=%s slug=%s admin_id=%s", entry.id, slug, user.id)
