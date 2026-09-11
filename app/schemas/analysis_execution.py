from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ScalarValue = str | int | float | bool


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    operator: Literal["equals", "not_equals", "greater_than", "less_than", "greater_equal", "less_equal", "between", "in", "date_range"]
    value: ScalarValue | None = None
    values: list[ScalarValue] | None = None


class AnalysisToolParameters(BaseModel):
    """Flat, explicit schema compatible with Gemini structured output."""

    model_config = ConfigDict(extra="forbid")
    group_by: list[str] | None = None
    metric: str | None = None
    aggregation: Literal["sum", "mean", "median", "count", "min", "max"] | None = None
    filters: list[FilterCondition] | None = None
    sort: Literal["asc", "desc"] | None = None
    limit: int | None = None
    columns: list[str] | None = None
    previous_filters: list[FilterCondition] | None = None
    current_filters: list[FilterCondition] | None = None
    baseline_filters: list[FilterCondition] | None = None
    dimension: str | None = None
    x: str | None = None
    y: str | None = None
    method: Literal["pearson", "spearman"] | None = None
    column: str | None = None
    date_column: str | None = None
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "yearly"] | None = None


class AnalysisExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["groupby_aggregate", "filter_dataset", "calculate_percentage_change", "calculate_contribution", "calculate_correlation", "distribution_summary", "time_series_aggregate"]
    parameters: AnalysisToolParameters
    interpretation_focus: str = Field(min_length=1, max_length=1000)


class ToolExecutionResult(BaseModel):
    tool: str
    columns_used: list[str]
    filters: list[dict[str, Any]]
    result: dict[str, Any] | list[Any]
    warnings: list[str]


class EvidenceInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interpretation: str = Field(min_length=1, max_length=3000)
    limitations: list[str] = Field(max_length=20)
