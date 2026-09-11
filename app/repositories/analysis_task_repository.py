from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_task import AnalysisTask


class AnalysisTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_many(self, tasks: list[AnalysisTask]) -> list[AnalysisTask]:
        self.session.add_all(tasks)
        await self.session.flush()
        return tasks

    async def list_for_plan(self, analysis_plan_id: UUID) -> list[AnalysisTask]:
        result = await self.session.execute(
            select(AnalysisTask)
            .where(AnalysisTask.analysis_plan_id == analysis_plan_id)
            .order_by(AnalysisTask.priority.asc(), AnalysisTask.task_code.asc())
        )
        return list(result.scalars().all())

    async def update_status(self, task: AnalysisTask, status: str, *, reason: str | None = None) -> AnalysisTask:
        task.status = status
        task.status_reason = reason
        await self.session.flush()
        return task
