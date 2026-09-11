from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ClaimEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_code: str = Field(min_length=1, max_length=16)
    status: Literal["accepted", "rejected", "needs_more_evidence"]
    evidence_strength: Literal["weak", "moderate", "strong"]
    issues: list[str] = Field(max_length=20)
    missing_analysis: list[str] = Field(max_length=20)
    corrected_wording: str | None = Field(default=None, max_length=3000)
