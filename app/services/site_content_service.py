import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_entry import ContentEntry
from app.models.user import User
from app.repositories.content_entry_repository import ContentEntryRepository
from app.schemas.email_template import EmailTemplatesContent
from app.schemas.site_content import LandingPageContent, PlansContent
from app.schemas.site_content import BlogContent
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

LANDING_CONTENT_TYPE = "landing_page"
LANDING_SLUG = "home"
BLOG_CONTENT_TYPE = "blog"
PLANS_CONTENT_TYPE = "plans_page"
PLANS_SLUG = "plans"
EMAIL_TEMPLATES_CONTENT_TYPE = "email_templates"
EMAIL_TEMPLATES_SLUG = "transactional"

DEFAULT_PLANS_CONTENT = PlansContent.model_validate({
    "enabled": False,
    "title": "Choose credits that fit your workflow.",
    "description": "Purchase question credits when you need more room to explore your data.",
    "note": "Credits are used when a new question is submitted. Retrying a failed analysis does not use another credit.",
    "plans": [
        {
            "name": "Starter", "description": "For occasional analysis and individual projects.",
            "price_label": "₹499", "amount_paise": 49900, "billing_label": "one-time", "credits": 25,
            "features": ["25 analysis questions", "All supported data sources", "Dashboard and PDF reports"],
            "button_label": "Purchase Starter", "button_href": "#", "highlighted": False,
        },
        {
            "name": "Growth", "description": "For teams that analyze business data regularly.",
            "price_label": "₹1,499", "amount_paise": 149900, "billing_label": "one-time", "credits": 100,
            "features": ["100 analysis questions", "All supported data sources", "Dashboard and PDF reports"],
            "button_label": "Purchase Growth", "button_href": "#", "highlighted": True,
        },
    ],
})


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

    async def get_plans(self, *, published_only: bool) -> ContentEntry | None:
        getter = self.entries.get_published if published_only else self.entries.get
        return await getter(PLANS_CONTENT_TYPE, PLANS_SLUG)

    async def update_plans(self, content: PlansContent, user: User) -> ContentEntry:
        entry = await self.entries.get(PLANS_CONTENT_TYPE, PLANS_SLUG)
        if entry is None:
            entry = ContentEntry(content_type=PLANS_CONTENT_TYPE, slug=PLANS_SLUG, status="published", content=content.model_dump(mode="json"), updated_by=user.id)
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
        logger.info("Plans content updated entry_id=%s version=%s admin_id=%s", entry.id, entry.version, user.id)
        return entry

    async def get_email_templates(self) -> ContentEntry | None:
        return await self.entries.get(EMAIL_TEMPLATES_CONTENT_TYPE, EMAIL_TEMPLATES_SLUG)

    async def resolve_email_templates(self) -> EmailTemplatesContent:
        from app.email_templates import DEFAULT_EMAIL_TEMPLATES

        try:
            entry = await self.get_email_templates()
            return EmailTemplatesContent.model_validate(entry.content) if entry is not None else DEFAULT_EMAIL_TEMPLATES
        except Exception:
            logger.exception("Saved email templates could not be resolved; using application defaults")
            return DEFAULT_EMAIL_TEMPLATES

    async def update_email_templates(self, content: EmailTemplatesContent, user: User) -> ContentEntry:
        entry = await self.get_email_templates()
        if entry is None:
            entry = ContentEntry(
                content_type=EMAIL_TEMPLATES_CONTENT_TYPE,
                slug=EMAIL_TEMPLATES_SLUG,
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
        logger.info("Email templates updated entry_id=%s version=%s admin_id=%s", entry.id, entry.version, user.id)
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
