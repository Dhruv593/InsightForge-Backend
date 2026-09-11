import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import User, UserSession

pytestmark = pytest.mark.anyio

REGISTER_PAYLOAD = {
    "name": "Dhruv Lad",
    "email": "dhruv@example.com",
    "password": "StrongPassword123!",
}


async def register_user(client: httpx.AsyncClient) -> dict[str, object]:
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201
    return response.json()


async def test_successful_registration(client: httpx.AsyncClient) -> None:
    body = await register_user(client)

    assert body["user"]["email"] == "dhruv@example.com"
    assert body["user"]["is_active"] is True
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_password_and_refresh_token_are_not_stored_raw(
    client: httpx.AsyncClient,
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    body = await register_user(client)

    async with test_session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        stored_session = (
            await session.execute(select(UserSession))
        ).scalar_one()

    assert user.password_hash != REGISTER_PAYLOAD["password"]
    assert user.password_hash.startswith("$argon2")
    assert stored_session.refresh_token_hash != body["refresh_token"]
    assert len(stored_session.refresh_token_hash) == 64


async def test_duplicate_registration_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    await register_user(client)
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_short_password_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={**REGISTER_PAYLOAD, "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_successful_login(client: httpx.AsyncClient) -> None:
    await register_user(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["email"],
            "password": REGISTER_PAYLOAD["password"],
        },
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == REGISTER_PAYLOAD["email"]
    assert response.json()["access_token"]
    assert response.json()["refresh_token"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("dhruv@example.com", "IncorrectPassword123!"),
        ("unknown@example.com", "StrongPassword123!"),
    ],
)
async def test_invalid_login_uses_generic_error(
    client: httpx.AsyncClient,
    email: str,
    password: str,
) -> None:
    await register_user(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid email or password.",
    }


async def test_me_accepts_valid_access_token(client: httpx.AsyncClient) -> None:
    registration = await register_user(client)
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registration['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == REGISTER_PAYLOAD["email"]


@pytest.mark.parametrize("authorization", [None, "Bearer not-a-valid-token"])
async def test_me_rejects_missing_or_invalid_token(
    client: httpx.AsyncClient,
    authorization: str | None,
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


async def test_access_and_refresh_token_types_are_not_interchangeable(
    client: httpx.AsyncClient,
) -> None:
    registration = await register_user(client)

    refresh_with_access = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": registration["access_token"]},
    )
    me_with_refresh = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registration['refresh_token']}"},
    )

    assert refresh_with_access.status_code == 401
    assert me_with_refresh.status_code == 401


async def test_refresh_rotates_token_and_prevents_reuse(
    client: httpx.AsyncClient,
) -> None:
    registration = await register_user(client)
    old_refresh_token = registration["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != old_refresh_token

    reuse_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh_token},
    )
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    registration = await register_user(client)
    refresh_token = registration["refresh_token"]

    logout_response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"success": True}

    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"
