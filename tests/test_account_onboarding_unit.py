from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.account_service import AccountService

pytestmark = pytest.mark.anyio


async def test_complete_onboarding_is_persisted_once():
    session = AsyncMock(spec=AsyncSession)
    service = AccountService(session)
    user = SimpleNamespace(onboarding_completed_at=None)

    result = await service.complete_onboarding(user)

    assert result is user
    assert user.onboarding_completed_at is not None
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)

    await service.complete_onboarding(user)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()
