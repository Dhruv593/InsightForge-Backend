from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MonitoringSummary(BaseModel):
    total_users: int
    active_sessions: int
    queued_analyses: int
    running_analyses: int
    completed_analyses: int
    failed_analyses: int
    average_duration_seconds: float | None


class ProviderMetric(BaseModel):
    provider: str
    total: int
    failed: int
    failure_rate: float


class AgentMetric(BaseModel):
    agent_name: str
    executions: int
    failures: int
    average_latency_ms: float | None


class FailedRunItem(BaseModel):
    id: UUID
    provider: str
    error_code: str | None
    error_message: str | None
    created_at: datetime


class MonitoringResponse(BaseModel):
    status: str = "operational"
    database_status: str = "connected"
    summary: MonitoringSummary
    providers: list[ProviderMetric]
    agents: list[AgentMetric]
    recent_failures: list[FailedRunItem]
    langsmith_project_url: str | None = None
