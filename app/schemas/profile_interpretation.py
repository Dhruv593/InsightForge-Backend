from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RelevantColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    role: Literal["metric", "dimension", "date", "potential_driver", "identifier", "other"]
    inferred_type: str = Field(min_length=1, max_length=100)
    relevance_reason: str = Field(min_length=1, max_length=1000)


class ProfileInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevant_columns: list[RelevantColumn] = Field(max_length=200)
    usable_date_columns: list[str] = Field(max_length=50)
    data_quality_constraints: list[str] = Field(max_length=50)
    excluded_columns: list[str] = Field(max_length=200)
    analysis_warnings: list[str] = Field(max_length=50)
