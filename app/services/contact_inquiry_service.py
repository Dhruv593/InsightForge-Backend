import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.email_templates import contact_reply_email
from app.models.contact_inquiry import ContactInquiry
from app.models.user import User
from app.repositories.contact_inquiry_repository import ContactInquiryRepository
from app.schemas.contact_inquiry import ContactInquiryStatus
from app.schemas.site_content import ContactRequest
from app.services.email_service import EmailDeliveryUnavailable, EmailService
from app.services.site_content_service import SiteContentService

logger = logging.getLogger(__name__)


class ContactInquiryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.inquiries = ContactInquiryRepository(session)

    async def create(self, payload: ContactRequest) -> ContactInquiry:
        inquiry = ContactInquiry(
            name=payload.name.strip(),
            email=str(payload.email).lower(),
            subject=(payload.subject or "Landing page enquiry").strip(),
            message=payload.message.strip(),
        )
        try:
            await self.inquiries.save(inquiry)
            await self.session.commit()
            await self.session.refresh(inquiry)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        logger.info(
            "Contact inquiry stored inquiry_id=%s",
            inquiry.id,
            extra={"event": "contact.inquiry.created", "inquiry_id": str(inquiry.id)},
        )
        return inquiry

    async def record_notification(self, inquiry: ContactInquiry, status: str) -> ContactInquiry:
        inquiry.notification_status = status
        await self._commit(inquiry)
        return inquiry

    async def list(self, *, status: ContactInquiryStatus | None = None) -> tuple[list[ContactInquiry], dict[str, int]]:
        return await self.inquiries.list(status=status), await self.inquiries.counts()

    async def get(self, inquiry_id: UUID) -> ContactInquiry:
        inquiry = await self.inquiries.get(inquiry_id)
        if inquiry is None:
            raise AppError("CONTACT_INQUIRY_NOT_FOUND", "Contact inquiry not found.", 404)
        return inquiry

    async def update_status(self, inquiry_id: UUID, status: ContactInquiryStatus) -> ContactInquiry:
        inquiry = await self.get(inquiry_id)
        inquiry.status = status
        await self._commit(inquiry)
        logger.info(
            "Contact inquiry status updated inquiry_id=%s status=%s",
            inquiry.id,
            status,
            extra={"event": "contact.inquiry.status_updated", "inquiry_id": str(inquiry.id), "status": status},
        )
        return inquiry

    async def reply(self, inquiry_id: UUID, message: str, admin: User) -> ContactInquiry:
        inquiry = await self.get(inquiry_id)
        settings = get_settings()
        templates = await SiteContentService(self.session).resolve_email_templates()
        email = contact_reply_email(
            contact_name=inquiry.name,
            original_subject=inquiry.subject,
            reply_message=message,
            frontend_url=settings.frontend_url,
            support_email=settings.support_email.strip() or settings.smtp_from_email.strip(),
            template=templates.contact_reply,
        )
        try:
            await EmailService().send_rendered(recipient=inquiry.email, email=email)
        except EmailDeliveryUnavailable as exc:
            raise AppError("CONTACT_REPLY_NOT_CONFIGURED", "Email delivery is not configured yet.", 503) from exc
        except Exception as exc:
            logger.exception(
                "Contact inquiry reply failed inquiry_id=%s",
                inquiry.id,
                extra={"event": "contact.inquiry.reply_failed", "inquiry_id": str(inquiry.id)},
            )
            raise AppError("CONTACT_REPLY_FAILED", "The reply could not be sent. Please try again.", 502) from exc

        inquiry.reply_message = message.strip()
        inquiry.replied_by = admin.id
        inquiry.replied_at = datetime.now(timezone.utc)
        inquiry.status = "replied"
        await self._commit(inquiry)
        logger.info(
            "Contact inquiry reply sent inquiry_id=%s admin_id=%s",
            inquiry.id,
            admin.id,
            extra={"event": "contact.inquiry.replied", "inquiry_id": str(inquiry.id), "admin_id": str(admin.id)},
        )
        return inquiry

    async def _commit(self, inquiry: ContactInquiry) -> None:
        try:
            await self.inquiries.save(inquiry)
            await self.session.commit()
            await self.session.refresh(inquiry)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
