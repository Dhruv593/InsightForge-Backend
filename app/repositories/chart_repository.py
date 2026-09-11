from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chart_spec import ChartSpec


class ChartRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create_many(self, charts: list[ChartSpec]) -> list[ChartSpec]:
        self.session.add_all(charts); await self.session.flush(); return charts
    async def list_for_run(self, run_id: UUID) -> list[ChartSpec]:
        result = await self.session.execute(select(ChartSpec).where(ChartSpec.analysis_run_id == run_id).order_by(ChartSpec.chart_code))
        return list(result.scalars().all())
