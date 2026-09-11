from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset_profile import DatasetProfile


class DatasetProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, dataset_id: UUID, profile_status: str) -> DatasetProfile:
        profile = DatasetProfile(
            dataset_id=dataset_id,
            profile_status=profile_status,
        )
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def get_by_dataset_id(self, dataset_id: UUID) -> DatasetProfile | None:
        result = await self.session.execute(
            select(DatasetProfile).where(DatasetProfile.dataset_id == dataset_id),
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        profile: DatasetProfile,
        **values: Any,
    ) -> DatasetProfile:
        for field_name, value in values.items():
            setattr(profile, field_name, value)
        await self.session.flush()
        return profile

    async def mark_failed(self, dataset_id: UUID) -> None:
        await self.session.execute(
            update(DatasetProfile)
            .where(DatasetProfile.dataset_id == dataset_id)
            .values(profile_status="failed"),
        )

    async def delete(self, profile: DatasetProfile) -> None:
        await self.session.delete(profile)
        await self.session.flush()
