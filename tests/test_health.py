import asyncio
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:password@localhost:5432/insightforge_test",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-with-at-least-32-bytes-not-for-production",
)

import httpx

from app.main import app


def test_health_check() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/api/v1/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "InsightForge API",
    }


def test_health_check_supports_head_uptime_probe() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.head("/api/v1/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
