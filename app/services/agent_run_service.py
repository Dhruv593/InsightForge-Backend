from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.repositories.agent_run_repository import AgentRunRepository


class AgentRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = AgentRunRepository(session)

    async def start(
        self,
        *,
        analysis_run_id: UUID,
        agent_name: str,
        provider: str,
        model: str,
        input_json: dict[str, Any],
        started_at: datetime,
    ) -> AgentRun:
        return await self.repository.create_running(
            analysis_run_id=analysis_run_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_json=input_json,
            started_at=started_at,
        )

    async def list_for_run(self, analysis_run_id: UUID) -> list[AgentRun]:
        return await self.repository.list_for_analysis_run(analysis_run_id)
