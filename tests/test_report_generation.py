"""Report generation and recovery with mocked providers and persistence."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.report import ReportAgent
from app.schemas.llm import LLMResult, LLMUsage
from app.services.analysis_execution_service import AnalysisExecutionService, StageAgentFailure
from app.services.stage9_service import Stage9Failure, Stage9Service


def report_service():
    service = Stage9Service.__new__(Stage9Service)
    service.session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service.reports = SimpleNamespace(create=AsyncMock())
    return service


def run_context():
    return SimpleNamespace(id=uuid4(), llm_provider="groq", query="Explain performance and recommend next steps.")


def state_context():
    return {
        "accepted_claims": [{"claim_code": "C1", "evidence_codes": ["E1"], "validated_text": "East leads."}],
        "evidence": [{"evidence_code": "E1", "result": [{"Region": "East", "value": 240}]}],
        "statistical_validations": [],
        "chart_specs": [{"chart_type": "bar", "evidence_codes": ["E1"]}],
    }


def report_payload(recommendation="Review East's orders before extending the approach. Track revenue and costs during a limited trial."):
    return {
        "executive_summary": "East leads with 240.",
        "key_findings": [{"claim_code": "C1", "finding": "East leads with 240.", "evidence_codes": ["E1"]}],
        "statistical_findings": [], "data_notes": [], "limitations": [],
        "recommendations": [recommendation],
    }


async def invoke_agent(_name, _inputs, invoke):
    return await invoke()


@pytest.mark.anyio
@pytest.mark.parametrize(("provider", "group", "metric", "recommendation"), [
    ("groq", "East", "Net_Revenue", "Review East's order mix because it leads recorded revenue. Check product costs before trying the same mix elsewhere."),
    ("gemini", "Support", "Resolution_Hours", "Review Support's unresolved cases because they take the longest to close. Check handoffs and track resolution time after a limited process change."),
])
async def test_generated_recommendations_use_selected_provider_and_verified_context(provider, group, metric, recommendation):
    service = report_service()
    run = run_context()
    run.llm_provider = provider
    run.query = f"Explain {metric} and recommend improvements."
    output = report_payload(recommendation)
    output["executive_summary"] = f"{group} has the highest {metric} at 240."
    output["key_findings"][0]["finding"] = output["executive_summary"]
    llm = SimpleNamespace(generate_structured=AsyncMock(return_value=LLMResult(
        provider=provider, model="mock", content=output, usage=LLMUsage(), latency_ms=1,
    )))
    service.report_agent = ReportAgent(llm)
    claims = [{"claim_code": "C1", "evidence_codes": ["E1"], "validated_text": output["executive_summary"]}]
    evidence = [
        {"evidence_code": "E1", "operation": {"metric": metric}, "result": [{"Group": group, "value": 240}]},
        {"evidence_code": "REJECTED", "result": {"value": 999}},
    ]
    actual = await service.create_report(
        run=run, claims=claims, evidence=evidence, validations=[],
        quality_warnings=[], charts=[], run_agent=invoke_agent,
    )

    assert actual["recommendations"] == [recommendation]
    call = llm.generate_structured.await_args.kwargs
    assert call["provider"] == provider
    payload = json.loads(call["messages"][1].content)
    assert payload["query"] == run.query
    assert payload["accepted_claims"] == claims
    assert payload["supporting_evidence"] == evidence[:1]
    assert service.reports.create.await_args.args[0].recommendations == [recommendation]
    service.session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_report_stage_uses_generated_report_and_preserves_charts():
    execution = AnalysisExecutionService.__new__(AnalysisExecutionService)
    execution.stage9 = SimpleNamespace(create_report=AsyncMock(return_value=report_payload()), create_fallback_report=AsyncMock())
    state = state_context()
    warnings = [{"message": "The period is incomplete."}]
    actual = await execution._generate_report(run=run_context(), state=state, quality_warnings=warnings, run_agent=invoke_agent)

    assert actual["recommendations"] == report_payload()["recommendations"]
    inputs = execution.stage9.create_report.await_args.kwargs
    assert inputs["claims"] == state["accepted_claims"]
    assert inputs["evidence"] == state["evidence"]
    assert inputs["charts"] == state["chart_specs"]
    assert inputs["quality_warnings"] == warnings
    execution.stage9.create_fallback_report.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [
    StageAgentFailure("LLM_TIMEOUT", "Provider unavailable."),
    StageAgentFailure("LLM_INVALID_RESPONSE", "Invalid response."),
    Stage9Failure("REPORT_VALIDATION_FAILED"),
])
async def test_report_stage_recovers_model_failures_without_losing_completed_work(failure):
    execution = AnalysisExecutionService.__new__(AnalysisExecutionService)
    fallback = report_payload("Review the available results before committing budget.")
    execution.stage9 = SimpleNamespace(create_report=AsyncMock(side_effect=failure), create_fallback_report=AsyncMock(return_value=fallback))
    state = state_context()
    actual = await execution._generate_report(run=run_context(), state=state, quality_warnings=[], run_agent=invoke_agent)

    assert actual == fallback
    assert execution.stage9.create_fallback_report.await_args.kwargs["evidence"] == state["evidence"]
    assert state["chart_specs"] == state_context()["chart_specs"]
    execution.stage9.create_fallback_report.assert_awaited_once()


@pytest.mark.anyio
async def test_report_stage_does_not_invoke_model_without_accepted_claims():
    execution = AnalysisExecutionService.__new__(AnalysisExecutionService)
    execution.stage9 = SimpleNamespace(create_report=AsyncMock(), create_fallback_report=AsyncMock(return_value={"key_findings": []}))
    state = {**state_context(), "accepted_claims": []}
    actual = await execution._generate_report(run=run_context(), state=state, quality_warnings=[], run_agent=invoke_agent)
    assert actual["key_findings"] == []
    execution.stage9.create_report.assert_not_awaited()
    execution.stage9.create_fallback_report.assert_awaited_once()


@pytest.mark.anyio
async def test_report_persistence_failure_goes_to_global_recovery_without_retrying_writes():
    execution = AnalysisExecutionService.__new__(AnalysisExecutionService)
    execution.stage9 = SimpleNamespace(create_report=AsyncMock(side_effect=Stage9Failure("REPORT_PERSISTENCE_FAILED")), create_fallback_report=AsyncMock())
    with pytest.raises(Stage9Failure, match="REPORT_PERSISTENCE_FAILED"):
        await execution._generate_report(run=run_context(), state=state_context(), quality_warnings=[], run_agent=invoke_agent)
    execution.stage9.create_fallback_report.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("defect", ["unknown_claim", "unrelated_number", "invented_target", "empty_findings", "bad_schema"])
async def test_report_rejects_unsupported_content_before_persistence(defect):
    service = report_service()
    state = state_context()
    state["accepted_claims"].append({"claim_code": "C2", "evidence_codes": ["E2"]})
    state["evidence"].append({"evidence_code": "E2", "result": {"value": 999}})
    payload = report_payload()
    if defect == "unknown_claim":
        payload["key_findings"][0]["claim_code"] = "C9"
    elif defect == "unrelated_number":
        payload["key_findings"][0]["finding"] = "East leads with 999."
    elif defect == "invented_target":
        payload["recommendations"] = ["Increase spend by 17%. Revenue will double."]
    elif defect == "empty_findings":
        payload["key_findings"] = []
    else:
        payload = {"recommendations": "not an array"}
    runner = AsyncMock(return_value=LLMResult(provider="groq", model="mock", content=payload, usage=LLMUsage(), latency_ms=1))
    with pytest.raises(Stage9Failure, match="REPORT_VALIDATION_FAILED"):
        await service.create_report(
            run=run_context(), claims=state["accepted_claims"], evidence=state["evidence"],
            validations=[], quality_warnings=[], charts=[], run_agent=runner,
        )
    service.reports.create.assert_not_awaited()
