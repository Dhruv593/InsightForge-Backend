from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.schemas.chart import VisualizationOutput
from app.schemas.claim import ClaimGenerationOutput
from app.schemas.claim_review import ClaimEvaluation
from app.schemas.llm import LLMResult, LLMUsage
from app.schemas.report import FinalReportOutput
from app.agents import ClaimGeneratorAgent, CriticAgent, ReportAgent, VisualizationAgent
from app.services.llm.gemini_provider import GeminiProvider
from app.services.analysis_output_service import AnalysisOutputFailure, AnalysisOutputService
from app.models.evidence import Evidence


def llm_result(content):
    return LLMResult(provider="gemini", model="mock", content=content, usage=LLMUsage(total_tokens=1), latency_ms=1)


def service():
    instance = AnalysisOutputService.__new__(AnalysisOutputService)
    instance.session = SimpleNamespace(add_all=Mock(), flush=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    instance.claims = SimpleNamespace(list_for_run=AsyncMock())
    instance.reviews = SimpleNamespace()
    instance.charts = SimpleNamespace(create_many=AsyncMock())
    instance.reports = SimpleNamespace(create=AsyncMock())
    instance.claim_models = {}
    return instance


class MockStructuredLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def generate_structured(self, *, provider, messages, response_model):
        self.calls.append((provider, response_model.__name__))
        return llm_result(self.responses[response_model])


@pytest.mark.anyio
async def test_all_stage9_agents_use_structured_outputs_and_selected_provider() -> None:
    responses = {
        ClaimGenerationOutput: {"claims": [{"claim_code": "C1", "claim_text": "North leads.", "claim_type": "descriptive", "evidence_codes": ["E1"]}]},
        ClaimEvaluation: {"claim_code": "C1", "status": "accepted", "evidence_strength": "strong", "issues": [], "missing_analysis": [], "corrected_wording": None},
        VisualizationOutput: {"charts": []},
        FinalReportOutput: {"executive_summary": "North leads.", "key_findings": [{"claim_code": "C1", "finding": "North leads.", "evidence_codes": ["E1"]}], "statistical_findings": [], "data_notes": [], "limitations": [], "recommendations": []},
    }
    llm = MockStructuredLLM(responses)
    await ClaimGeneratorAgent(llm).run(provider="groq", query="Summarize", evidence=[], validations=[])
    await CriticAgent(llm).run(provider="groq", query="Summarize", claim={}, evidence=[], validations=[], quality_warnings=[])
    await VisualizationAgent(llm).run(provider="groq", query="Summarize", claims=[], evidence=[], columns=[])
    await ReportAgent(llm).run(provider="groq", query="Summarize", claims=[], evidence=[], validations=[], quality_warnings=[], charts=[])
    assert llm.calls == [("groq", "ClaimGenerationOutput"), ("groq", "ClaimEvaluation"), ("groq", "VisualizationOutput"), ("groq", "FinalReportOutput")]


def test_stage9_gemini_schemas_only_contain_explicit_objects() -> None:
    for response_model in (ClaimGenerationOutput, ClaimEvaluation, VisualizationOutput, FinalReportOutput):
        schema = GeminiProvider._build_gemini_schema(response_model)

        def inspect(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    assert value.get("properties")
                assert "additionalProperties" not in value
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        inspect(schema)


@pytest.mark.parametrize(("provider_code", "normalized"), [("C1", "C1"), ("c01", "C1"), ("claim_2", "C2"), ("Finding 03", "C3")])
def test_claim_codes_accept_common_provider_variants(provider_code, normalized) -> None:
    output = ClaimGenerationOutput.model_validate({"claims": [{"claim_code": provider_code, "claim_text": "North leads.", "claim_type": "descriptive", "evidence_codes": ["E1"]}]})
    assert output.claims[0].claim_code == normalized


@pytest.mark.anyio
async def test_claim_generation_links_known_evidence_and_rejects_ungrounded_numbers() -> None:
    instance = service()
    evidence_model = Evidence(id=uuid4(), analysis_run_id=uuid4(), analysis_task_id=uuid4(), evidence_code="E1", method="groupby_aggregate", columns_used=["Region", "Revenue"], filters=[], operation={}, result=[{"Region": "North", "value": 10}], interpretation="North leads with 10.", limitations=[])
    instance.evidence_repo = SimpleNamespace(list_for_run=AsyncMock(return_value=[evidence_model]))
    instance.claims = SimpleNamespace(create_many=AsyncMock())
    run = SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Which region leads?")
    evidence = [{"evidence_code": "E1", "method": "groupby_aggregate", "result": [{"Region": "North", "value": 10}], "interpretation": "North leads with 10.", "limitations": []}]

    async def valid_runner(*_args):
        return llm_result({"claims": [{"claim_code": "C1", "claim_text": "North leads with 10.", "claim_type": "descriptive", "evidence_codes": ["E1"]}]})

    claims = await instance.generate_claims(run=run, evidence=evidence, validations=[], run_agent=valid_runner)
    assert claims[0]["evidence_codes"] == ["E1"]
    persisted = instance.claims.create_many.call_args.args[0][0]
    assert persisted.evidence_items == [evidence_model]

    async def ungrounded_runner(*_args):
        return llm_result({"claims": [{"claim_code": "C1", "claim_text": "North leads with 99.", "claim_type": "descriptive", "evidence_codes": ["E1"]}]})

    with pytest.raises(AnalysisOutputFailure, match="CLAIM_VALIDATION_FAILED"):
        await instance.generate_claims(run=run, evidence=evidence, validations=[], run_agent=ungrounded_runner)


@pytest.mark.anyio
async def test_critic_keeps_only_accepted_claims_and_persists_all_review_statuses() -> None:
    instance = service()
    labels = ["North leads", "South trails", "Evidence is limited", "Pattern is stable"]
    claims = [
        {"claim_code": f"C{index}", "claim_text": labels[index - 1], "claim_type": "descriptive", "evidence_codes": ["E1"]}
        for index in range(1, 5)
    ]
    instance.claim_models = {item["claim_code"]: SimpleNamespace(id=uuid4(), status="pending_review") for item in claims}
    statuses = {"C1": "accepted", "C2": "rejected", "C3": "needs_more_evidence", "C4": "accepted"}

    async def runner(agent_name, _input, _invoke):
        code = agent_name.split(":", 1)[1]
        corrected = "The observed pattern is stable." if code == "C4" else None
        return llm_result({"claim_code": code, "status": statuses[code], "evidence_strength": "strong" if statuses[code] == "accepted" else "weak", "issues": [], "missing_analysis": ["Add a longer period."] if code == "C3" else [], "corrected_wording": corrected})

    reviews, accepted = await instance.review_claims(
        run=SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Summarize"),
        claims=claims,
        evidence=[{"evidence_code": "E1", "method": "groupby_aggregate", "result": [{"Region": "North", "value": 10}]}],
        validations=[],
        quality_warnings=[],
        run_agent=runner,
    )

    assert [item["status"] for item in reviews] == ["accepted", "rejected", "needs_more_evidence", "accepted"]
    assert [item["claim_code"] for item in accepted] == ["C1", "C4"]
    assert accepted[1]["validated_text"] == "The observed pattern is stable."
    assert [instance.claim_models[f"C{index}"].status for index in range(1, 5)] == list(statuses.values())
    assert len(instance.session.add_all.call_args.args[0]) == 4
    instance.session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_visualization_supports_no_chart_and_rejects_unknown_evidence() -> None:
    instance = service()
    run = SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Compare regions")

    async def no_chart_runner(*_args):
        return llm_result({"charts": []})

    assert await instance.create_charts(run=run, claims=[], evidence=[], columns=[], run_agent=no_chart_runner) == []
    instance.charts.create_many.assert_not_awaited()

    async def valid_runner(*_args):
        return llm_result({"charts": [{"needed": True, "chart_type": "bar", "title": "Revenue", "x_column": "Region", "y_column": "Revenue", "group_column": None, "evidence_codes": ["E1"], "purpose": "Compare regions."}]})

    charts = await instance.create_charts(
        run=run,
        claims=[{"claim_code": "C1", "evidence_codes": ["E1"]}],
        evidence=[{"evidence_code": "E1", "result": [{"Region": "North", "value": 10}], "filters": []}],
        columns=[{"name": "Region"}, {"name": "Revenue"}],
        run_agent=valid_runner,
    )
    assert charts[0]["chart_config"]["values"] == [10]
    instance.charts.create_many.assert_awaited_once()

    async def invalid_runner(*_args):
        return llm_result({"charts": [{"needed": True, "chart_type": "bar", "title": "Revenue", "x_column": "Region", "y_column": "Revenue", "group_column": None, "evidence_codes": ["E9"], "purpose": "Compare regions."}]})

    with pytest.raises(AnalysisOutputFailure, match="CHART_SPEC_INVALID"):
        await instance.create_charts(run=run, claims=[], evidence=[], columns=[{"name": "Region"}, {"name": "Revenue"}], run_agent=invalid_runner)


@pytest.mark.anyio
async def test_explicit_chart_request_uses_verified_evidence_when_model_returns_no_chart() -> None:
    instance = service()
    run = SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Show total revenue by region as a bar chart")

    async def empty_runner(*_args):
        return llm_result({"charts": []})

    charts = await instance.create_charts(
        run=run,
        claims=[{"claim_code": "C1", "evidence_codes": ["E1"]}],
        evidence=[{
            "evidence_code": "E1",
            "method": "groupby_aggregate",
            "operation": {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"},
            "result": [{"Region": "North", "value": 100}, {"Region": "South", "value": 80}],
            "filters": [],
        }],
        columns=[{"name": "Region"}, {"name": "Revenue"}],
        run_agent=empty_runner,
    )

    assert charts[0]["chart_type"] == "bar"
    assert charts[0]["chart_config"]["labels"] == ["North", "South"]
    assert charts[0]["chart_config"]["values"] == [100, 80]
    instance.charts.create_many.assert_awaited_once()


@pytest.mark.anyio
async def test_visualization_supplements_one_model_chart_with_other_chartable_evidence() -> None:
    instance = service()
    run = SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Analyze revenue across regions, products, and months")

    async def one_chart_runner(*_args):
        return llm_result({"charts": [{"needed": True, "chart_type": "bar", "title": "Revenue by Region", "x_column": "Region", "y_column": "Revenue", "group_column": None, "evidence_codes": ["E1"], "purpose": "Compare regions."}]})

    evidence = [
        {"evidence_code": "E1", "method": "groupby_aggregate", "operation": {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"}, "result": [{"Region": "North", "value": 100}], "filters": []},
        {"evidence_code": "E2", "method": "groupby_aggregate", "operation": {"group_by": ["Product"], "metric": "Revenue", "aggregation": "sum"}, "result": [{"Product": "A", "value": 90}], "filters": []},
        {"evidence_code": "E3", "method": "time_series_aggregate", "operation": {"date_column": "Date", "metric": "Revenue", "aggregation": "sum", "frequency": "monthly"}, "result": [{"Date": "2026-01-31", "Revenue": 80}], "filters": []},
    ]
    charts = await instance.create_charts(
        run=run,
        claims=[{"claim_code": "C1", "evidence_codes": ["E1", "E2", "E3"]}],
        evidence=evidence,
        columns=[{"name": "Date"}, {"name": "Region"}, {"name": "Product"}, {"name": "Revenue"}],
        run_agent=one_chart_runner,
    )

    assert [chart["chart_type"] for chart in charts] == ["bar", "bar", "line"]
    assert [chart["evidence_codes"] for chart in charts] == [["E1"], ["E2"], ["E3"]]


def test_chart_data_is_derived_from_evidence_and_report_is_readable() -> None:
    config = AnalysisOutputService._chart_data(
        {"chart_type": "bar", "x_column": "Region", "y_column": "Revenue", "group_column": None},
        [{"result": [{"Region": "North", "value": 310.0}, {"Region": "South", "value": 250.0}]}],
    )
    assert config == {"labels": ["North", "South"], "values": [310.0, 250.0], "x_column": "Region", "y_column": "value"}
    text = AnalysisOutputService.format_report({"executive_summary": "North led revenue.", "key_findings": [{"finding": "North recorded 310.0."}], "statistical_findings": [], "data_notes": ["Missing values were retained."], "limitations": [], "recommendations": []})
    assert "Key findings:" in text
    assert "Data notes:" in text
    assert "evidence_code" not in text


@pytest.mark.anyio
async def test_fallback_deduplicates_equivalent_tasks_but_keeps_other_dimensions():
    instance = service()
    source = {"evidence_code": "E1", "method": "groupby_aggregate", "operation": {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"}, "result": [{"Region": "North", "value": 100}, {"Region": "South", "value": 80}], "filters": []}
    duplicate = {**source, "evidence_code": "E2", "result": [{"Region": "South", "value": 80.0}, {"Region": "North", "value": 100.0}]}
    product = {**source, "evidence_code": "E3", "operation": {"group_by": ["Product"], "metric": "Revenue", "aggregation": "sum"}, "result": [{"Product": "A", "value": 100}, {"Product": "B", "value": 80}]}
    charts = await instance.create_fallback_charts(run=SimpleNamespace(id=uuid4(), query="Revenue contribution per region in percentage format with supporting visuals"), claims=[], evidence=[source, duplicate, product], columns=[{"name": name} for name in ["Region", "Revenue", "Product"]])
    assert len(charts) == 2
    assert [chart["chart_code"] for chart in charts] == ["CH1", "CH2"]
    assert [chart["x_column"] for chart in charts] == ["Region", "Product"]


@pytest.mark.anyio
async def test_model_metric_alias_repaired_and_distinct_filters_preserved():
    instance = service()
    source = {"evidence_code": "E1", "method": "groupby_aggregate", "operation": {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"}, "result": [{"Region": "North", "value": 100}], "filters": []}
    filtered = {**source, "evidence_code": "E2", "filters": [{"column": "Product", "operator": "eq", "value": "A"}]}
    async def runner(*_args):
        return llm_result({"charts": [{"needed": True, "chart_type": "pie", "title": "Contribution", "x_column": "Region", "y_column": "value", "evidence_codes": [code], "purpose": "Regional revenue share"} for code in ["E1", "E1", "E2"]]})
    charts = await instance.create_charts(run=SimpleNamespace(id=uuid4(), llm_provider="gemini", query="pie chart"), claims=[], evidence=[source, filtered], columns=[{"name": name} for name in ["Region", "Revenue", "Product"]], run_agent=runner)
    assert len(charts) == 2
    assert all(chart["y_column"] == "Revenue" for chart in charts)
    assert charts[0]["filters"] != charts[1]["filters"]


@pytest.mark.parametrize(("query", "aggregation", "values", "expected"), [
    ("Analyze revenue by region", "sum", [100, 80], "donut"),
    ("What is each region's share of revenue?", "sum", [100, 80], "pie"),
    ("Compare average revenue", "mean", [100, 80], "bar"),
    ("Analyze profit", "sum", [100, -80], "bar"),
    ("Compare regions using a bar chart", "sum", [100, 80], "bar"),
])
def test_automatic_chart_selection_respects_data_and_explicit_requests(query, aggregation, values, expected):
    evidence = [{"evidence_code": "E1", "method": "groupby_aggregate",
                 "operation": {"group_by": ["Region"], "metric": "Revenue", "aggregation": aggregation},
                 "result": [{"Region": str(index), "value": value} for index, value in enumerate(values)]}]
    assert AnalysisOutputService._fallback_chart(query, evidence).chart_type == expected


@pytest.mark.anyio
async def test_report_rejects_findings_not_backed_by_an_accepted_claim() -> None:
    instance = service()

    async def runner(*_args):
        return llm_result({
            "executive_summary": "The accepted evidence is limited.",
            "key_findings": [{"claim_code": "C2", "finding": "Unsupported finding.", "evidence_codes": ["E2"]}],
            "statistical_findings": [], "data_notes": [], "limitations": [], "recommendations": [],
        })

    with pytest.raises(AnalysisOutputFailure, match="REPORT_VALIDATION_FAILED"):
        await instance.create_report(
            run=SimpleNamespace(id=uuid4(), llm_provider="gemini", query="Summarize"),
            claims=[{"claim_code": "C1", "evidence_codes": ["E1"], "validated_text": "Accepted finding."}],
            evidence=[{"evidence_code": "E1", "result": {"value": 10}}],
            validations=[], quality_warnings=[], charts=[], run_agent=runner,
        )
