from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_run import AnalysisRun
from app.models.conversation import Conversation
from app.models.dataset import Dataset


class AnalysisRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, analysis_run: AnalysisRun) -> AnalysisRun:
        self.session.add(analysis_run)
        await self.session.flush()
        return analysis_run

    async def get_by_id_for_user(self, analysis_run_id: UUID, user_id: UUID) -> AnalysisRun | None:
        result = await self.session.execute(
            select(AnalysisRun)
            .join(Conversation, Conversation.id == AnalysisRun.conversation_id)
            .join(Dataset, Dataset.id == AnalysisRun.dataset_id)
            .where(
                AnalysisRun.id == analysis_run_id,
                AnalysisRun.user_id == user_id,
                Conversation.user_id == user_id,
                Dataset.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(self, conversation_id: UUID, user_id: UUID) -> list[AnalysisRun]:
        result = await self.session.execute(
            select(AnalysisRun)
            .join(Conversation, Conversation.id == AnalysisRun.conversation_id)
            .join(Dataset, Dataset.id == AnalysisRun.dataset_id)
            .where(
                AnalysisRun.conversation_id == conversation_id,
                AnalysisRun.user_id == user_id,
                Conversation.user_id == user_id,
                Dataset.user_id == user_id,
            )
            .order_by(AnalysisRun.created_at.desc())
        )
        return list(result.scalars().all())

    async def find_duplicate(self, *, dataset_id: UUID, user_id: UUID, normalized_query: str) -> AnalysisRun | None:
        result = await self.session.execute(
            select(AnalysisRun)
            .where(
                AnalysisRun.dataset_id == dataset_id,
                AnalysisRun.user_id == user_id,
                func.lower(func.trim(AnalysisRun.query)) == normalized_query.lower(),
                AnalysisRun.status.in_(("pending", "running", "completed")),
            )
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_pending(self, limit: int = 20) -> list[AnalysisRun]:
        result = await self.session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.status == "pending")
            .order_by(AnalysisRun.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active_for_user(self, user_id: UUID) -> list[AnalysisRun]:
        result = await self.session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.user_id == user_id, AnalysisRun.status.in_(("pending", "running")))
            .order_by(AnalysisRun.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_active_for_user(self, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(AnalysisRun.id)).where(
                AnalysisRun.user_id == user_id,
                AnalysisRun.status.in_(("pending", "running")),
            )
        )
        return int(result.scalar_one())

    async def requeue_interrupted(self) -> int:
        result = await self.session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.status == "running")
            .values(status="pending", started_at=None, completed_at=None, error_code=None, error_message=None)
        )
        return int(result.rowcount or 0)

    async def queue_position(self, analysis_run: AnalysisRun) -> int | None:
        if analysis_run.status != "pending":
            return None
        result = await self.session.execute(
            select(func.count(AnalysisRun.id)).where(
                AnalysisRun.status == "pending",
                AnalysisRun.created_at <= analysis_run.created_at,
            )
        )
        return int(result.scalar_one())

    async def cancel(self, analysis_run: AnalysisRun) -> AnalysisRun:
        analysis_run.status = "cancelled"
        analysis_run.completed_at = datetime.now(timezone.utc)
        analysis_run.error_code = None
        analysis_run.error_message = None
        await self.session.flush()
        return analysis_run

    async def update_status(
        self, analysis_run: AnalysisRun, status: str, *, started_at: datetime | None = None,
        completed_at: datetime | None = None, error_code: str | None = None,
        error_message: str | None = None,
    ) -> AnalysisRun:
        analysis_run.status = status
        analysis_run.started_at = started_at
        analysis_run.completed_at = completed_at
        analysis_run.error_code = error_code
        analysis_run.error_message = error_message
        await self.session.flush()
        return analysis_run

    async def claim_pending(
        self,
        *,
        analysis_run_id: UUID,
        user_id: UUID,
        started_at: datetime,
    ) -> AnalysisRun | None:
        result = await self.session.execute(
            update(AnalysisRun)
            .where(
                AnalysisRun.id == analysis_run_id,
                AnalysisRun.user_id == user_id,
                AnalysisRun.status == "pending",
            )
            .values(
                status="running",
                started_at=started_at,
                completed_at=None,
                error_code=None,
                error_message=None,
            )
            .returning(AnalysisRun)
        )
        return result.scalar_one_or_none()
