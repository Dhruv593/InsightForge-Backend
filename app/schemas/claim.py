from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClaimType = Literal["descriptive", "comparative", "diagnostic", "statistical", "relationship", "limitation"]
ClaimStatus = Literal["pending_review", "accepted", "rejected", "needs_more_evidence"]


class CandidateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_code: str = Field(description="Sequential claim identifier using C1, C2, C3, and so on.", pattern=r"^C[1-9][0-9]?$", max_length=16)
    claim_text: str = Field(description="Concise evidence-backed finding with no calculations or invented values.", min_length=1, max_length=3000)
    claim_type: ClaimType = Field(description="Controlled classification of the analytical claim.")
    evidence_codes: list[str] = Field(description="Existing evidence identifiers that directly support this claim, such as E1.", max_length=20)

    @field_validator("claim_code", mode="before")
    @classmethod
    def normalize_claim_code(cls, value):
        if not isinstance(value, str):
            return value
        match = re.search(r"(\d{1,2})\s*$", value.strip())
        if match and 1 <= int(match.group(1)) <= 99:
            return f"C{int(match.group(1))}"
        return value.strip().upper()


class ClaimGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[CandidateClaim] = Field(description="A small ordered list of candidate claims; use sequential claim codes beginning with C1.")


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_run_id: UUID
    claim_code: str
    claim_text: str
    claim_type: str
    status: str
    evidence_codes: list[str] = Field(default_factory=list)
    review: dict | None = None
    created_at: datetime
    updated_at: datetime


class ClaimListResponse(BaseModel):
    items: list[ClaimResponse]
    total: int
