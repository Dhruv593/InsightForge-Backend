from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset


class DatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, dataset: Dataset) -> Dataset:
        self.session.add(dataset)
        await self.session.flush()
        return dataset

    async def get_for_user(
        self,
        *,
        dataset_id: UUID,
        user_id: UUID,
    ) -> Dataset | None:
        result = await self.session.execute(
            select(Dataset).where(
                Dataset.id == dataset_id,
                Dataset.user_id == user_id,
            ),
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[Dataset]:
        result = await self.session.execute(
            select(Dataset)
            .where(Dataset.user_id == user_id)
            .order_by(Dataset.created_at.desc()),
        )
        return list(result.scalars().all())

    async def delete(self, dataset: Dataset) -> None:
        await self.session.delete(dataset)
        await self.session.flush()
