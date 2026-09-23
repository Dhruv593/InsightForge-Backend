import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.core.exceptions import AppError
from app.core.config import get_settings
from app.db.session import get_db_session
from app.email_templates import credit_adjusted_email
from app.repositories.user_repository import UserRepository
from app.schemas.admin_user import AdminAccessUpdate, AdminUserItem, AdminUserListResponse, CreditAdjustment
from app.services.email_service import EmailService
from app.services.site_content_service import SiteContentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    _: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    search: Annotated[str, Query(max_length=200)] = "",
) -> AdminUserListResponse:
    users, total = await UserRepository(session).list_users(search=search)
    return AdminUserListResponse(items=[AdminUserItem.model_validate(user) for user in users], total=total)


@router.patch("/{user_id}/admin-access", response_model=AdminUserItem)
async def update_admin_access(
    user_id: UUID,
    payload: AdminAccessUpdate,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminUserItem:
    if user_id == admin.id:
        raise AppError("ADMIN_SELF_ROLE_CHANGE", "You cannot change your own admin access.", 409)
    repository = UserRepository(session)
    target = await repository.get_by_id(user_id)
    if target is None:
        raise AppError("USER_NOT_FOUND", "User not found.", 404)
    if not payload.is_admin and target.admin_managed_by_environment:
        raise AppError(
            "ENVIRONMENT_ADMIN_PROTECTED",
            "This owner's access is managed by the server environment and cannot be removed here.",
            409,
        )
    target.admin_access = payload.is_admin
    await session.commit()
    await session.refresh(target)
    return AdminUserItem.model_validate(target)


@router.patch("/{user_id}/credits", response_model=AdminUserItem)
async def adjust_user_credits(
    user_id: UUID,
    payload: CreditAdjustment,
    _: AdminUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminUserItem:
    repository = UserRepository(session)
    target = await repository.get_by_id(user_id)
    if target is None:
        raise AppError("USER_NOT_FOUND", "User not found.", 404)
    remaining = await repository.adjust_credits(user_id, payload.delta)
    if remaining is None:
        raise AppError("INVALID_CREDIT_ADJUSTMENT", "Credits cannot be reduced below zero.", 422)
    target.credits = remaining
    await session.commit()
    await session.refresh(target)
    settings = get_settings()
    templates = await SiteContentService(session).resolve_email_templates()
    email = credit_adjusted_email(
        user_name=target.name,
        previous_balance=remaining - payload.delta,
        adjustment=payload.delta,
        new_balance=remaining,
        reason=payload.reason,
        frontend_url=settings.frontend_url,
        support_email=settings.support_email.strip() or settings.smtp_from_email.strip(),
        template=templates.credit_adjusted,
    )
    try:
        await EmailService().send_rendered(recipient=target.email, email=email)
    except Exception:
        logger.exception("Credit adjustment email could not be delivered user_id=%s", target.id)
    return AdminUserItem.model_validate(target)
