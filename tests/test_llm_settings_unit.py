from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_auth_service
from app.api.llm_settings import get_llm_settings_service, router
from app.core.exceptions import AppError, app_error_handler
from app.models import AnalysisRun, Conversation, DatasetProfile, Message, User
from app.schemas.llm_settings import LLMSettingsUpdate
from app.services.analysis_run_service import AnalysisRunService
from app.services.llm_settings_service import LLMSettingsService

pytestmark = pytest.mark.anyio


def make_service():
    settings = SimpleNamespace(
        default_llm_provider="gemini",
        gemini_api_key=SecretStr("private-gemini-key"), gemini_model="test-gemini-model",
        groq_api_key=SecretStr("private-groq-key"), groq_model="test-groq-model",
        openai_api_key=SecretStr("private-openai-key"), openai_model="test-openai-model",
        anthropic_api_key=SecretStr("private-anthropic-key"), anthropic_model="test-anthropic-model",
    )
    service = LLMSettingsService(AsyncMock(spec=AsyncSession), settings=settings)
    service.repository = AsyncMock()
    service.repository.get.return_value = None
    return service


async def test_default_and_persisted_selection_never_expose_keys():
    service = make_service()
    assert await service.selected_provider() == "gemini"
    result = await service.get()
    assert result.updated_at is None
    assert all(item.configured for item in result.options)
    assert "private-" not in result.model_dump_json()
    service.repository.get.return_value = SimpleNamespace(provider="groq", updated_at=None)
    assert await service.selected_provider() == "groq"


async def test_admin_can_save_configured_provider():
    service = make_service()
    user = SimpleNamespace(id=uuid4(), is_admin=True)
    service.repository.set_provider.return_value = SimpleNamespace(
        provider="groq", updated_at=datetime.now(timezone.utc),
    )
    result = await service.update(LLMSettingsUpdate(provider="groq"), user)
    assert result.provider == "groq"
    service.repository.set_provider.assert_awaited_once_with("groq", user.id)
    service.session.commit.assert_awaited_once()


@pytest.mark.parametrize("missing", ["key", "model"])
async def test_unconfigured_provider_cannot_be_saved(missing):
    service = make_service()
    if missing == "key":
        service.settings.groq_api_key = SecretStr("")
    else:
        service.settings.groq_model = ""
    with pytest.raises(AppError) as error:
        await service.update(LLMSettingsUpdate(provider="groq"), SimpleNamespace(id=uuid4(), is_admin=True))
    assert error.value.code == "LLM_PROVIDER_NOT_CONFIGURED"
    service.repository.set_provider.assert_not_awaited()


async def test_non_admin_cannot_update_service():
    service = make_service()
    with pytest.raises(AppError) as error:
        await service.update(LLMSettingsUpdate(provider="groq"), SimpleNamespace(id=uuid4(), is_admin=False))
    assert error.value.status_code == 403
    service.repository.set_provider.assert_not_awaited()


async def test_failed_save_rolls_back():
    service = make_service()
    service.session.commit.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError):
        await service.update(LLMSettingsUpdate(provider="groq"), SimpleNamespace(id=uuid4(), is_admin=True))
    service.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("role,status", [("anonymous", 401), ("user", 403), ("admin", 200)])
async def test_admin_routes_enforce_access(method, role, status):
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    service = make_service()
    service.repository.set_provider.return_value = SimpleNamespace(provider="groq", updated_at=None)
    auth = AsyncMock()
    auth.get_user_from_access_token.return_value = SimpleNamespace(id=uuid4(), is_admin=role == "admin")
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_llm_settings_service] = lambda: service
    headers = {} if role == "anonymous" else {"Authorization": "Bearer test-token"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/admin/settings/llm", headers=headers,
                                        json={"provider": "groq"} if method == "PUT" else None)
    assert response.status_code == status
    assert "private-" not in response.text
    if status != 200:
        service.repository.set_provider.assert_not_awaited()
        service.repository.get.assert_not_awaited()


def test_invalid_provider_and_extra_fields_rejected():
    for payload in ({"provider": "unknown"}, {"provider": "groq", "api_key": "secret"}):
        with pytest.raises(ValidationError):
            LLMSettingsUpdate(**payload)


@pytest.mark.parametrize("requested", [None, "gemini", "arbitrary-value"])
async def test_new_runs_ignore_client_provider(requested):
    service = AnalysisRunService(AsyncMock(spec=AsyncSession))
    user = User(id=uuid4())
    conversation = Conversation(id=uuid4(), user_id=user.id, dataset_id=uuid4())
    service.conversation_service.get_conversation = AsyncMock(return_value=conversation)
    service.llm_settings.selected_provider = AsyncMock(return_value="groq")
    service.profiles.get_by_dataset_id = AsyncMock(return_value=DatasetProfile(profile_status="completed"))
    service.runs.find_duplicate = AsyncMock(return_value=None)
    service.runs.count_active_for_user = AsyncMock(return_value=0)
    service.users.get_by_id_for_update = AsyncMock(return_value=User(id=user.id, credits=5))
    service.users.consume_credit = AsyncMock()
    service.runs.create = AsyncMock()
    service.conversations.touch = AsyncMock()
    service.message_service.create_user_message = AsyncMock(return_value=Message())
    _, run = await service.create_pending_run(conversation.id, "Show revenue", requested, user)
    assert run.llm_provider == "groq"
    service.llm_settings.selected_provider.assert_awaited_once()
    service.users.consume_credit.assert_not_awaited()


async def test_retry_does_not_forward_user_or_previous_provider():
    service = AnalysisRunService(AsyncMock(spec=AsyncSession))
    user = User(id=uuid4())
    original = AnalysisRun(id=uuid4(), conversation_id=uuid4(), query="Show revenue",
                           llm_provider="gemini", status="failed")
    service.get_run = AsyncMock(return_value=original)
    service.create_pending_run = AsyncMock(return_value=(Message(), AnalysisRun()))
    await service.retry_run(original.id, user, provider="gemini")
    service.create_pending_run.assert_awaited_once_with(
        original.conversation_id, original.query, None, user, force=True,
    )
