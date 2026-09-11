from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StatisticalValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method_requested: str = Field(min_length=1, max_length=255)
    test_type: Literal["independent_t_test", "welch_t_test", "mann_whitney_u", "anova", "chi_square", "pearson", "spearman"]
    columns: list[str] = Field(min_length=2, max_length=3)
    group_column: str | None
    assumptions_to_check: list[str] = Field(max_length=10)


class StatisticalTestResult(BaseModel):
    method_used: str
    statistic: float | None
    p_value: float | None
    effect_size: float | None
    confidence_interval: dict[str, float] | None
    assumptions: dict[str, Any]
    is_significant: bool | None
    is_valid: bool
    warnings: list[str]


class StatisticalInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interpretation: str = Field(min_length=1, max_length=3000)


class StatisticalValidationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_run_id: UUID
    analysis_task_id: UUID
    evidence_id: UUID | None
    method_requested: str
    method_used: str
    assumptions: dict[str, Any]
    p_value: float | None
    effect_size: float | None
    confidence_interval: dict[str, Any] | None
    is_significant: bool | None
    is_valid: bool
    warnings: list[str]
    interpretation: str
    created_at: datetime


class StatisticalValidationListResponse(BaseModel):
    items: list[StatisticalValidationResponse]
    total: int
