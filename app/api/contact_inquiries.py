from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.db.session import get_db_session
from app.schemas.contact_inquiry import ContactInquiryListResponse, ContactInquiryReply, ContactInquiryResponse, ContactInquiryStatus, ContactInquiryStatusUpdate
from app.services.contact_inquiry_service import ContactInquiryService

router = APIRouter(prefix="/admin/contact-inquiries", tags=["contact-inquiries"])


def service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> ContactInquiryService:
    return ContactInquiryService(session)


@router.get("", response_model=ContactInquiryListResponse)
async def list_contact_inquiries(
    _: AdminUser,
    inquiries: Annotated[ContactInquiryService, Depends(service)],
    inquiry_status: ContactInquiryStatus | None = Query(default=None, alias="status"),
) -> ContactInquiryListResponse:
    items, counts = await inquiries.list(status=inquiry_status)
    return ContactInquiryListResponse(items=items, total=counts["total"], counts=counts)


@router.get("/{inquiry_id}", response_model=ContactInquiryResponse)
async def get_contact_inquiry(inquiry_id: UUID, _: AdminUser, inquiries: Annotated[ContactInquiryService, Depends(service)]) -> ContactInquiryResponse:
    return ContactInquiryResponse.model_validate(await inquiries.get(inquiry_id))


@router.patch("/{inquiry_id}", response_model=ContactInquiryResponse)
async def update_contact_inquiry(inquiry_id: UUID, payload: ContactInquiryStatusUpdate, _: AdminUser, inquiries: Annotated[ContactInquiryService, Depends(service)]) -> ContactInquiryResponse:
    return ContactInquiryResponse.model_validate(await inquiries.update_status(inquiry_id, payload.status))


@router.post("/{inquiry_id}/reply", response_model=ContactInquiryResponse)
async def reply_to_contact_inquiry(inquiry_id: UUID, payload: ContactInquiryReply, user: AdminUser, inquiries: Annotated[ContactInquiryService, Depends(service)]) -> ContactInquiryResponse:
    return ContactInquiryResponse.model_validate(await inquiries.reply(inquiry_id, payload.message, user))
