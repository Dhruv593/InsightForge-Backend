import asyncio
import os
from collections.abc import AsyncIterator

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:password@localhost:5432/insightforge_test",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-secret-key-with-at-least-32-bytes-not-for-production",
)
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "test-cloud")
os.environ.setdefault("CLOUDINARY_API_KEY", "test-api-key")
os.environ.setdefault("CLOUDINARY_API_SECRET", "test-api-secret")

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models import User, UserSession


@pytest.fixture(scope="session")
def anyio_backend() -> tuple[str, dict[str, object]]:
    backend_options: dict[str, object] = {}
    if os.name == "nt":
        backend_options["loop_factory"] = asyncio.SelectorEventLoop
    return "asyncio", backend_options


@pytest.fixture(scope="session")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    database_url = os.getenv("TEST_DATABASE_URL") or dotenv_values(".env").get(
        "TEST_DATABASE_URL",
    )
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests.")

    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        pytest.fail("TEST_DATABASE_URL must point to a database containing 'test'.")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def test_session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def client(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    async with test_session_factory() as cleanup_session:
        await cleanup_session.execute(delete(UserSession))
        await cleanup_session.execute(delete(User))
        await cleanup_session.commit()
