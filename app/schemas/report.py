from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_code: str = Field(min_length=1, max_length=16)
    finding: str = Field(min_length=1, max_length=3000)
    evidence_codes: list[str] = Field(min_length=1, max_length=20)


class FinalReportOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executive_summary: str = Field(min_length=1, max_length=5000)
    key_findings: list[ReportFinding] = Field(max_length=12)
    statistical_findings: list[str] = Field(max_length=20)
    data_notes: list[str] = Field(max_length=20)
    limitations: list[str] = Field(max_length=20)
    recommendations: list[str] = Field(max_length=20)


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_run_id: UUID
    executive_summary: str
    key_findings: list[dict]
    statistical_findings: list[str]
    data_notes: list[str]
    limitations: list[str]
    recommendations: list[str]
    report: dict
    created_at: datetime
    updated_at: datetime
