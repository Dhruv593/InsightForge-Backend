from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import case, distinct, func, select, text

from app.api.dependencies import AdminUser
from app.core.config import get_settings
from app.db.session import AsyncSessionFactory
from app.models.analysis_run import AnalysisRun
from app.models.agent_run import AgentRun
from app.models.user import User
from app.models.user_session import UserSession
from app.schemas.monitoring import AgentMetric, FailedRunItem, MonitoringResponse, MonitoringSummary, ProviderMetric

router = APIRouter(prefix="/monitoring", tags=["owner-monitoring"])


@router.get("/overview", response_model=MonitoringResponse)
async def monitoring_overview(_: AdminUser) -> MonitoringResponse:
    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as session:
        await session.execute(text("SELECT 1"))
        total_users = await session.scalar(select(func.count(User.id))) or 0
        active_sessions = await session.scalar(select(func.count(distinct(UserSession.user_id))).where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)) or 0
        status_rows = dict((await session.execute(select(AnalysisRun.status, func.count(AnalysisRun.id)).group_by(AnalysisRun.status))).all())
        average_duration = await session.scalar(
            select(func.avg(func.extract("epoch", AnalysisRun.completed_at - AnalysisRun.started_at))).where(
                AnalysisRun.started_at.is_not(None), AnalysisRun.completed_at.is_not(None)
            )
        )
        provider_rows = (await session.execute(
            select(
                AnalysisRun.llm_provider,
                func.count(AnalysisRun.id),
                func.sum(case((AnalysisRun.status == "failed", 1), else_=0)),
            ).group_by(AnalysisRun.llm_provider)
        )).all()
        failed_rows = (await session.execute(
            select(AnalysisRun).where(AnalysisRun.status == "failed").order_by(AnalysisRun.created_at.desc()).limit(20)
        )).scalars().all()
        agent_rows = (await session.execute(
            select(
                AgentRun.agent_name,
                func.count(AgentRun.id),
                func.sum(case((AgentRun.status == "failed", 1), else_=0)),
                func.avg(AgentRun.latency_ms),
            ).group_by(AgentRun.agent_name).order_by(AgentRun.agent_name)
        )).all()

    providers = [ProviderMetric(provider=provider, total=total, failed=failed or 0, failure_rate=round(((failed or 0) / total) * 100, 1) if total else 0) for provider, total, failed in provider_rows]
    settings = get_settings()
    return MonitoringResponse(
        summary=MonitoringSummary(
            total_users=total_users,
            active_sessions=active_sessions,
            queued_analyses=status_rows.get("pending", 0),
            running_analyses=status_rows.get("running", 0),
            completed_analyses=status_rows.get("completed", 0),
            failed_analyses=status_rows.get("failed", 0),
            average_duration_seconds=round(float(average_duration), 1) if average_duration is not None else None,
        ),
        providers=providers,
        agents=[AgentMetric(agent_name=name, executions=total, failures=failed or 0, average_latency_ms=round(float(latency), 1) if latency is not None else None) for name, total, failed, latency in agent_rows],
        recent_failures=[FailedRunItem(id=run.id, provider=run.llm_provider, error_code=run.error_code, error_message=run.error_message, created_at=run.created_at) for run in failed_rows],
        langsmith_project_url=settings.langsmith_project_url or None,
    )
