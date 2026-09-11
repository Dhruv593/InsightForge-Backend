from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.evidence import Evidence


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def create(self, evidence: Evidence) -> Evidence:
        self.session.add(evidence); await self.session.flush(); return evidence
    async def list_for_run(self, run_id: UUID) -> list[Evidence]:
        result = await self.session.execute(select(Evidence).where(Evidence.analysis_run_id == run_id).order_by(Evidence.created_at, Evidence.evidence_code))
        return list(result.scalars().all())
