from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.claim import Claim


class ClaimRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create_many(self, claims: list[Claim]) -> list[Claim]:
        self.session.add_all(claims); await self.session.flush(); return claims
    async def list_for_run(self, run_id: UUID) -> list[Claim]:
        result = await self.session.execute(select(Claim).options(selectinload(Claim.evidence_items), selectinload(Claim.review)).where(Claim.analysis_run_id == run_id).order_by(Claim.claim_code))
        return list(result.scalars().unique().all())
    async def update_status(self, claim: Claim, status: str) -> Claim:
        claim.status = status; await self.session.flush(); return claim
