import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_entry import ContentEntry
from app.models.user import User
from app.repositories.content_entry_repository import ContentEntryRepository
from app.schemas.email_template import EmailTemplatesContent
from app.schemas.site_content import LandingPageContent, LegalPagesContent, PlansContent
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
LEGAL_CONTENT_TYPE = "legal_pages"
LEGAL_SLUG = "policies"

DEFAULT_PLANS_CONTENT = PlansContent.model_validate({
    "enabled": False,
    "title": "Choose credits that fit your workflow.",
    "description": "Purchase question credits when you need more room to explore your data.",
    "note": "One credit is used only after an analysis finishes successfully. Failed or cancelled analyses do not use credits.",
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

DEFAULT_LEGAL_CONTENT = LegalPagesContent.model_validate({
    "privacy": {
        "title": "Privacy Policy",
        "description": "How Tatparya collects, uses, stores, and protects information.",
        "effective_date": "18 September 2026",
        "introduction": "This policy applies to the Tatparya web application and its related services.",
        "sections": [
            {"heading": "Information we collect", "paragraphs": ["Account information such as your name, email address, verification status, and securely hashed password.", "Datasets you upload, dataset profiles, questions, analysis results, reports, and conversation history.", "Technical and security information such as request identifiers, timestamps, error details, and sign-in sessions."]},
            {"heading": "How we use information", "paragraphs": ["Provide authentication, dataset analysis, visualizations, reports, and account support.", "Protect the service, investigate failures, prevent abuse, and improve reliability.", "Send verification, password-reset, and service-related messages when email delivery is configured."]},
            {"heading": "Service providers", "paragraphs": ["Tatparya may use hosting, database, file-storage, email, observability, Google sign-in, and language-model providers selected by the service operator. Dataset content or questions are sent to an LLM provider only when required to perform the analysis you request.", "Agent tracing is designed to use metadata-only mode unless the operator explicitly changes that configuration."]},
            {"heading": "Storage and retention", "paragraphs": ["Account and analysis data are retained while your account is active or as needed to operate and secure the service.", "You can delete your account from Account settings. This removes application records associated with the account, subject to provider backups and legal retention obligations."]},
            {"heading": "Security", "paragraphs": ["Tatparya uses access controls, encrypted HTTPS transport, limited request sizes, rate limits, and protected server-side secrets. No internet service can guarantee absolute security."]},
            {"heading": "Your choices", "paragraphs": ["You may review and update your profile, revoke sessions, change your password, or delete your account from Account settings.", "For privacy requests that cannot be completed in the product, contact the organization or administrator who provided your Tatparya access."]},
            {"heading": "Children", "paragraphs": ["Tatparya is intended for business users and is not directed to children under 13."]},
            {"heading": "Changes to this policy", "paragraphs": ["Material changes will be reflected by updating the effective date on this page."]},
        ],
    },
    "terms": {
        "title": "Terms and Conditions",
        "description": "The rules and responsibilities that apply when using Tatparya.",
        "effective_date": "18 September 2026",
        "introduction": "These terms apply to the Tatparya web application and its related services.",
        "sections": [
            {"heading": "Using Tatparya", "paragraphs": ["You must provide accurate account information, protect your credentials, and use the service only for lawful business purposes.", "You are responsible for ensuring that you have the right to upload and analyze the data you submit."]},
            {"heading": "Acceptable use", "paragraphs": ["Do not upload malicious files, attempt unauthorized access, interfere with the service, evade usage limits, or use Tatparya to violate another person’s rights.", "Do not treat the service as a substitute for professional legal, medical, financial, or regulatory advice."]},
            {"heading": "Analysis results", "paragraphs": ["Tatparya uses automated calculations and language models. Results can contain mistakes and should be reviewed before making material business decisions.", "Recommendations are informational. You remain responsible for decisions made using the service."]},
            {"heading": "Your content", "paragraphs": ["You retain ownership of the datasets and content you submit. You authorize Tatparya and its configured service providers to process that content only as needed to provide and secure the service."]},
            {"heading": "Availability and changes", "paragraphs": ["Features may change, be suspended, or become unavailable. The operator may apply reasonable limits to protect service reliability and other users."]},
            {"heading": "Account suspension and termination", "paragraphs": ["Access may be limited or terminated for misuse, security risk, legal requirements, or material violation of these terms. You may delete your account through Account settings."]},
            {"heading": "Disclaimers and liability", "paragraphs": ["The service is provided on an as available basis. To the extent permitted by law, the operator does not guarantee uninterrupted operation or that every analysis will be complete or error-free.", "Liability is limited to the extent permitted by applicable law. Consumer rights that cannot legally be excluded remain unaffected."]},
            {"heading": "Changes to these terms", "paragraphs": ["Continued use after updated terms take effect means you accept the revised terms. Material changes will be reflected by updating the effective date."]},
        ],
    },
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

    async def get_legal_pages(self, *, published_only: bool) -> ContentEntry | None:
        getter = self.entries.get_published if published_only else self.entries.get
        return await getter(LEGAL_CONTENT_TYPE, LEGAL_SLUG)

    async def update_legal_pages(self, content: LegalPagesContent, user: User) -> ContentEntry:
        entry = await self.entries.get(LEGAL_CONTENT_TYPE, LEGAL_SLUG)
        if entry is None:
            entry = ContentEntry(content_type=LEGAL_CONTENT_TYPE, slug=LEGAL_SLUG, status="published", content=content.model_dump(mode="json"), updated_by=user.id)
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
        logger.info("Legal pages updated entry_id=%s version=%s admin_id=%s", entry.id, entry.version, user.id)
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
