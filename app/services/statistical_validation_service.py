from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AnalysisRunNotFoundError
from app.models.statistical_validation import StatisticalValidation
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.repositories.statistical_validation_repository import StatisticalValidationRepository


class StatisticalValidationPersistenceError(Exception):
    code = "STATISTICAL_VALIDATION_FAILED"


class StatisticalValidationService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = StatisticalValidationRepository(session); self.runs = AnalysisRunRepository(session)
    async def create(self, *, run_id, task_id, evidence_id, content) -> StatisticalValidation:
        request, result = content["request"], content["result"]
        try:
            return await self.repository.create(StatisticalValidation(analysis_run_id=run_id, analysis_task_id=task_id, evidence_id=evidence_id, method_requested=request["method_requested"], method_used=result["method_used"], assumptions=result["assumptions"], p_value=result["p_value"], effect_size=result["effect_size"], confidence_interval=result["confidence_interval"], is_significant=result["is_significant"], is_valid=result["is_valid"], warnings=result["warnings"], interpretation=content["interpretation"]))
        except Exception as exc:
            raise StatisticalValidationPersistenceError from exc
    async def list_owned(self, run_id: UUID, user_id: UUID) -> list[StatisticalValidation]:
        if await self.runs.get_by_id_for_user(run_id, user_id) is None: raise AnalysisRunNotFoundError
        return await self.repository.list_for_run(run_id)
