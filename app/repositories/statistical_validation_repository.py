from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.statistical_validation import StatisticalValidation


class StatisticalValidationRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create(self, item: StatisticalValidation) -> StatisticalValidation:
        self.session.add(item); await self.session.flush(); return item
    async def list_for_run(self, run_id: UUID) -> list[StatisticalValidation]:
        result = await self.session.execute(select(StatisticalValidation).where(StatisticalValidation.analysis_run_id == run_id).order_by(StatisticalValidation.created_at))
        return list(result.scalars().all())
