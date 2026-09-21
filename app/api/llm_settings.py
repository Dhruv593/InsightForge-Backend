from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.db.session import get_db_session
from app.schemas.llm_settings import LLMSettingsResponse, LLMSettingsUpdate
from app.services.llm_settings_service import LLMSettingsService

router = APIRouter(prefix="/admin/settings/llm", tags=["admin-settings"])


def get_llm_settings_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> LLMSettingsService:
    return LLMSettingsService(session)


@router.get("", response_model=LLMSettingsResponse)
async def get_llm_settings(_: AdminUser, service: Annotated[LLMSettingsService, Depends(get_llm_settings_service)]) -> LLMSettingsResponse:
    return await service.get()


@router.put("", response_model=LLMSettingsResponse)
async def update_llm_settings(payload: LLMSettingsUpdate, user: AdminUser, service: Annotated[LLMSettingsService, Depends(get_llm_settings_service)]) -> LLMSettingsResponse:
    return await service.update(payload, user)
