from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    InvalidLLMProviderError,
    MessageEmptyError,
    QueryTooLongError,
)
from app.models import AnalysisRun, Conversation, Dataset, DatasetProfile, Message
from app.models.dataset_profile import DatasetProfileStatus
from app.models.user import User
from app.services.analysis_run_service import AnalysisRunService

pytestmark = pytest.mark.anyio


async def _register(client: httpx.AsyncClient, suffix: str = "owner") -> dict[str, object]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": suffix.title(),
            "email": f"{suffix}@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201
    return response.json()


def _headers(auth: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


async def _dataset(
    factory: async_sessionmaker[AsyncSession], auth: dict[str, object], *, profiled: bool
) -> UUID:
    dataset = Dataset(
        user_id=UUID(str(auth["user"]["id"])),
        original_file_name="revenue.csv",
        stored_file_name=f"{uuid4()}.csv",
        file_type="csv",
        mime_type="text/csv",
        file_size=128,
        cloudinary_url="https://res.cloudinary.com/test-cloud/raw/upload/revenue.csv",
        cloudinary_public_id=f"tests/{uuid4()}",
        cloudinary_resource_type="raw",
        upload_status="uploaded",
    )
    async with factory() as session:
        session.add(dataset)
        await session.flush()
        if profiled:
            session.add(
                DatasetProfile(
                    dataset_id=dataset.id,
                    profile_status=DatasetProfileStatus.COMPLETED.value,
                )
            )
        await session.commit()
        return dataset.id


async def _conversation(
    client: httpx.AsyncClient, auth: dict[str, object], dataset_id: UUID,
    title: str | None = "Revenue Analysis",
) -> dict[str, object]:
    payload: dict[str, object] = {"dataset_id": str(dataset_id)}
    if title is not None:
        payload["title"] = title
    response = await client.post(
        "/api/v1/conversations", json=payload, headers=_headers(auth)
    )
    assert response.status_code == 201
    return response.json()


async def test_conversation_crud_and_default_title(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    auth = await _register(client)
    dataset_id = await _dataset(test_session_factory, auth, profiled=False)
    created = await _conversation(client, auth, dataset_id, title=None)
    assert created["title"] == "New Analysis"

    listing = await client.get("/api/v1/conversations", headers=_headers(auth))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    conversation_id = created["id"]
    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=_headers(auth)
    )
    assert detail.status_code == 200

    updated = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"title": "Q3 Revenue Investigation"},
        headers=_headers(auth),
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Q3 Revenue Investigation"


async def test_conversation_rejects_unowned_dataset_and_cross_user_access(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _register(client, "owner")
    stranger = await _register(client, "stranger")
    dataset_id = await _dataset(test_session_factory, owner, profiled=False)
    conversation = await _conversation(client, owner, dataset_id)

    create = await client.post(
        "/api/v1/conversations",
        json={"dataset_id": str(dataset_id)},
        headers=_headers(stranger),
    )
    detail = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=_headers(stranger)
    )
    assert create.status_code == 404
    assert create.json()["error"]["code"] == "DATASET_NOT_FOUND"
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


async def test_list_returns_only_owned_conversations_and_supports_dataset_filter(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _register(client, "owner")
    stranger = await _register(client, "stranger")
    first = await _dataset(test_session_factory, owner, profiled=False)
    second = await _dataset(test_session_factory, owner, profiled=False)
    foreign = await _dataset(test_session_factory, stranger, profiled=False)
    await _conversation(client, owner, first, "First")
    await _conversation(client, owner, second, "Second")
    await _conversation(client, stranger, foreign, "Foreign")

    listing = await client.get("/api/v1/conversations", headers=_headers(owner))
    filtered = await client.get(
        "/api/v1/conversations", params={"dataset_id": str(first)}, headers=_headers(owner)
    )
    assert listing.json()["total"] == 2
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["dataset_id"] == str(first)


async def test_query_requires_completed_profile(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    auth = await _register(client)
    dataset_id = await _dataset(test_session_factory, auth, profiled=False)
    conversation = await _conversation(client, auth, dataset_id)
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/query",
        json={"query": "Why did revenue decline?", "llm_provider": "gemini"},
        headers=_headers(auth),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATASET_NOT_PROFILED"


@pytest.mark.parametrize("provider", ["gemini", "groq", "GEMINI", " Groq "])
async def test_query_creates_linked_message_and_pending_run(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
    provider: str,
) -> None:
    auth = await _register(client)
    dataset_id = await _dataset(test_session_factory, auth, profiled=True)
    conversation = await _conversation(client, auth, dataset_id)
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/query",
        json={"query": " Why did revenue decline? ", "llm_provider": provider},
        headers=_headers(auth),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["analysis_run"]["status"] == "pending"
    assert body["analysis_run"]["llm_provider"] == provider.strip().lower()
    assert body["message"]["role"] == "user"
    assert body["message"]["message_type"] == "text"
    assert body["message"]["analysis_run_id"] == body["analysis_run"]["id"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"query": "", "llm_provider": "gemini"}, "MESSAGE_EMPTY"),
        ({"query": "   ", "llm_provider": "groq"}, "MESSAGE_EMPTY"),
        ({"query": "x" * 5001, "llm_provider": "gemini"}, "QUERY_TOO_LONG"),
        ({"query": "question", "llm_provider": "openai"}, "INVALID_LLM_PROVIDER"),
    ],
)
async def test_query_validation(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
    payload: dict[str, str],
    code: str,
) -> None:
    auth = await _register(client)
    dataset_id = await _dataset(test_session_factory, auth, profiled=True)
    conversation = await _conversation(client, auth, dataset_id)
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/query",
        json=payload,
        headers=_headers(auth),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


async def test_message_history_and_run_reads_enforce_ownership(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await _register(client, "owner")
    stranger = await _register(client, "stranger")
    dataset_id = await _dataset(test_session_factory, owner, profiled=True)
    conversation = await _conversation(client, owner, dataset_id)
    run_ids = []
    for query in ("First question", "Second question"):
        response = await client.post(
            f"/api/v1/conversations/{conversation['id']}/query",
            json={"query": query, "llm_provider": "gemini"},
            headers=_headers(owner),
        )
        run_ids.append(response.json()["analysis_run"]["id"])

    messages = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(owner)
    )
    runs = await client.get(
        f"/api/v1/conversations/{conversation['id']}/analysis-runs", headers=_headers(owner)
    )
    one_run = await client.get(f"/api/v1/analysis-runs/{run_ids[0]}", headers=_headers(owner))
    assert [item["content"] for item in messages.json()["items"]] == ["First question", "Second question"]
    assert runs.json()["total"] == 2
    assert one_run.status_code == 200

    assert (await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=_headers(stranger)
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/conversations/{conversation['id']}/analysis-runs", headers=_headers(stranger)
    )).status_code == 404
    assert (await client.get(
        f"/api/v1/analysis-runs/{run_ids[0]}", headers=_headers(stranger)
    )).status_code == 404


async def test_delete_conversation_cascades_messages_and_runs_only(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    auth = await _register(client)
    dataset_id = await _dataset(test_session_factory, auth, profiled=True)
    conversation = await _conversation(client, auth, dataset_id)
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/query",
        json={"query": "Question", "llm_provider": "groq"},
        headers=_headers(auth),
    )
    deleted = await client.delete(
        f"/api/v1/conversations/{conversation['id']}", headers=_headers(auth)
    )
    assert deleted.status_code == 200

    async with test_session_factory() as session:
        assert await session.get(Dataset, dataset_id) is not None
        assert (await session.scalar(select(func.count()).select_from(Conversation))) == 0
        assert (await session.scalar(select(func.count()).select_from(Message))) == 0
        assert (await session.scalar(select(func.count()).select_from(AnalysisRun))) == 0


async def test_query_rolls_back_when_message_creation_fails() -> None:
    session = AsyncMock(spec=AsyncSession)
    service = AnalysisRunService(session)
    user = User(id=uuid4(), name="Owner", email="owner@example.com", password_hash="hash")
    conversation = Conversation(id=uuid4(), user_id=user.id, dataset_id=uuid4(), title="Analysis")
    profile = DatasetProfile(
        dataset_id=conversation.dataset_id,
        profile_status=DatasetProfileStatus.COMPLETED.value,
    )
    service.conversation_service.get_conversation = AsyncMock(return_value=conversation)
    service.profiles.get_by_dataset_id = AsyncMock(return_value=profile)
    service.runs.find_duplicate = AsyncMock(return_value=None)
    service.runs.create = AsyncMock(side_effect=lambda run: run)
    service.message_service.create_user_message = AsyncMock(
        side_effect=SQLAlchemyError("forced failure")
    )

    with pytest.raises(SQLAlchemyError):
        await service.create_pending_run(conversation.id, "Question", "gemini", user)

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_stage5_validation_helpers() -> None:
    assert AnalysisRunService._normalize_provider(" GEMINI ") == "gemini"
    with pytest.raises(InvalidLLMProviderError):
        AnalysisRunService._normalize_provider("openai")
    with pytest.raises(MessageEmptyError):
        AnalysisRunService._normalize_query("  ")
    with pytest.raises(QueryTooLongError):
        AnalysisRunService._normalize_query("x" * 5001)
