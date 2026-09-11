from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AnalysisType = Literal[
    "aggregation", "comparison", "segmentation", "correlation",
    "statistical_test", "regression", "time_series", "distribution",
    "data_quality",
]


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
    objective: str = Field(min_length=1, max_length=1000)
    analysis_type: AnalysisType
    required_columns: list[str] = Field(min_length=1, max_length=50)
    method: str = Field(min_length=1, max_length=1000)
    priority: int = Field(ge=1, le=100)
    depends_on: list[str] = Field(max_length=20)


class AnalysisPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: str = Field(min_length=1, max_length=50)
    objective: str = Field(min_length=1, max_length=2000)
    target_metric: str | None = Field(max_length=255)
    analysis_strategy: str = Field(min_length=1, max_length=4000)
    requires_statistics: bool
    requires_visualization: bool
    tasks: list[PlannedTask] = Field(min_length=1)
    completion_criteria: list[str] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)


class AnalysisTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_code: str
    objective: str
    analysis_type: str
    required_columns: list[str]
    depends_on: list[str]
    method: str
    priority: int
    status: str
    status_reason: str | None
    created_at: datetime
    updated_at: datetime


class AnalysisPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_run_id: UUID
    question_type: str
    objective: str
    target_metric: str | None
    analysis_strategy: str
    requires_statistics: bool
    requires_visualization: bool
    status: str
    completion_criteria: list[str]
    limitations: list[str]
    tasks: list[AnalysisTaskResponse]
    created_at: datetime
    updated_at: datetime
