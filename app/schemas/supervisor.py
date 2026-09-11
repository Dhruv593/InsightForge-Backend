from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_type: Literal[
        "descriptive", "diagnostic", "comparative", "statistical",
        "predictive", "data_quality", "unsupported",
    ]
    objective: str = Field(min_length=1, max_length=1000)
    target_metrics: list[str] = Field(max_length=20)
    relevant_dimensions: list[str] = Field(max_length=30)
    requires_statistics: bool
    requires_visualization: bool
    can_answer_with_available_data: bool
    missing_requirements: list[str] = Field(max_length=20)
