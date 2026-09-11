from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis_plan import AnalysisPlan


class AnalysisPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, plan: AnalysisPlan) -> AnalysisPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def get_by_analysis_run_id(self, analysis_run_id: UUID) -> AnalysisPlan | None:
        result = await self.session.execute(
            select(AnalysisPlan)
            .options(selectinload(AnalysisPlan.tasks))
            .where(AnalysisPlan.analysis_run_id == analysis_run_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, plan: AnalysisPlan) -> None:
        await self.session.delete(plan)
        await self.session.flush()
