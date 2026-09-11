from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AnalysisRunNotFoundError
from app.models.evidence import Evidence
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.evidence_repository import EvidenceRepository


class EvidencePersistenceError(Exception):
    code = "EVIDENCE_PERSISTENCE_FAILED"


class EvidenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = EvidenceRepository(session); self.runs = AnalysisRunRepository(session)
    async def create(self, *, run_id, task_id, code, content) -> Evidence:
        tool = content["tool_result"]; interpretation = content["interpretation"]
        try:
            return await self.repository.create(Evidence(analysis_run_id=run_id, analysis_task_id=task_id, evidence_code=code, method=tool["tool"], columns_used=tool["columns_used"], filters=tool["filters"], operation=content["selection"]["parameters"], result=tool["result"], interpretation=interpretation["interpretation"], limitations=interpretation["limitations"] + tool["warnings"]))
        except Exception as exc:
            raise EvidencePersistenceError from exc
    async def list_owned(self, run_id: UUID, user_id: UUID) -> list[Evidence]:
        if await self.runs.get_by_id_for_user(run_id, user_id) is None: raise AnalysisRunNotFoundError
        return await self.repository.list_for_run(run_id)
