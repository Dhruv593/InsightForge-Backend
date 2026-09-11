from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.analysis_constants import AgentRunStatus
from app.models.agent_run import AgentRun


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_running(
        self,
        *,
        analysis_run_id: UUID,
        agent_name: str,
        provider: str,
        model: str,
        input_json: dict[str, Any],
        started_at: datetime,
    ) -> AgentRun:
        agent_run = AgentRun(
            analysis_run_id=analysis_run_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            status=AgentRunStatus.RUNNING.value,
            input_json=input_json,
            started_at=started_at,
        )
        self.session.add(agent_run)
        await self.session.flush()
        return agent_run

    async def mark_completed(
        self,
        agent_run: AgentRun,
        *,
        output_json: dict[str, Any],
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        latency_ms: int,
        completed_at: datetime,
    ) -> AgentRun:
        agent_run.status = AgentRunStatus.COMPLETED.value
        agent_run.output_json = output_json
        agent_run.prompt_tokens = prompt_tokens
        agent_run.completion_tokens = completion_tokens
        agent_run.total_tokens = total_tokens
        agent_run.latency_ms = latency_ms
        agent_run.completed_at = completed_at
        agent_run.error_code = None
        agent_run.error_message = None
        await self.session.flush()
        return agent_run

    async def mark_failed(
        self,
        agent_run: AgentRun,
        *,
        error_code: str,
        error_message: str,
        completed_at: datetime,
    ) -> AgentRun:
        agent_run.status = AgentRunStatus.FAILED.value
        agent_run.error_code = error_code
        agent_run.error_message = error_message
        agent_run.completed_at = completed_at
        await self.session.flush()
        return agent_run

    async def list_for_analysis_run(self, analysis_run_id: UUID) -> list[AgentRun]:
        result = await self.session.execute(
            select(AgentRun)
            .where(AgentRun.analysis_run_id == analysis_run_id)
            .order_by(AgentRun.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, agent_run_id: UUID) -> AgentRun | None:
        return await self.session.get(AgentRun, agent_run_id)
