from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChartType = Literal["line", "bar", "horizontal_bar", "grouped_bar", "stacked_bar", "scatter", "histogram", "boxplot", "pie", "donut", "heatmap", "waterfall"]


class ChartRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    needed: bool
    chart_type: ChartType | None = None
    title: str | None = Field(default=None, max_length=300)
    x_column: str | None = Field(default=None, max_length=255)
    y_column: str | None = Field(default=None, max_length=255)
    group_column: str | None = Field(default=None, max_length=255)
    evidence_codes: list[str] = Field(max_length=20)
    purpose: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_needed_fields(self):
        if self.needed and (not self.chart_type or not self.title or not self.evidence_codes or not self.purpose):
            raise ValueError("A needed chart requires type, title, evidence, and purpose.")
        return self


class VisualizationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    charts: list[ChartRecommendation]


class ChartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_run_id: UUID
    chart_code: str
    chart_type: str
    title: str
    x_column: str | None
    y_column: str | None
    group_column: str | None
    evidence_codes: list[str]
    filters: list[dict[str, Any]]
    chart_config: dict[str, Any]
    purpose: str
    created_at: datetime


class ChartListResponse(BaseModel):
    items: list[ChartResponse]
    total: int
