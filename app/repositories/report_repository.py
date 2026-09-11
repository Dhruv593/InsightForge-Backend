from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.report import Report


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create(self, report: Report) -> Report:
        self.session.add(report); await self.session.flush(); return report
    async def get_for_run(self, run_id: UUID) -> Report | None:
        result = await self.session.execute(select(Report).where(Report.analysis_run_id == run_id))
        return result.scalar_one_or_none()
