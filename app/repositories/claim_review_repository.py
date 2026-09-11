from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.claim_review import ClaimReview


class ClaimReviewRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create(self, review: ClaimReview) -> ClaimReview:
        self.session.add(review); await self.session.flush(); return review
    async def list_for_run(self, run_id: UUID) -> list[ClaimReview]:
        result = await self.session.execute(select(ClaimReview).where(ClaimReview.analysis_run_id == run_id).order_by(ClaimReview.created_at))
        return list(result.scalars().all())
