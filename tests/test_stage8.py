from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pandas as pd
import pytest

from app.agents.analyst import AnalystAgent, NumericGroundingError
from app.agents.statistical_validator import StatisticalValidatorAgent
from app.schemas.analysis_execution import AnalysisExecutionRequest, EvidenceInterpretation
from app.schemas.llm import LLMResult, LLMUsage
from app.schemas.statistical_validation import (
    StatisticalInterpretation,
    StatisticalValidationRequest,
)
from app.services.analysis_task_execution_service import (
    AnalysisTaskExecutionService,
    TaskExecutionFailure,
)
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.base import LLMProviderError
from app.tools.analytics import AnalyticsToolRegistry, ToolValidationError
from app.tools.statistics import StatisticalToolRegistry


@pytest.fixture
def business_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": ["2026-01-05", "2026-01-20", "2026-02-05", "2026-02-20", "2026-03-05", "2026-03-20"],
            "Region": ["North", "South", "North", "South", "North", "South"],
            "Revenue": [100.0, 80.0, 120.0, 100.0, 90.0, 70.0],
            "Units_Sold": [10, 8, 12, 10, 9, 7],
            "Channel": ["Online", "Retail", "Online", "Retail", "Retail", "Online"],
        }
    )


def test_analytics_registry_executes_all_supported_operations_without_mutation(business_frame) -> None:
    original = business_frame.copy(deep=True)
    tools = AnalyticsToolRegistry()

    grouped = tools.execute(business_frame, "groupby_aggregate", {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"})
    filtered = tools.execute(business_frame, "filter_dataset", {"columns": ["Region", "Revenue"], "filters": [{"column": "Revenue", "operator": "greater_than", "value": 90}]})
    changed = tools.execute(business_frame, "calculate_percentage_change", {"metric": "Revenue", "previous_filters": [{"column": "Date", "operator": "date_range", "values": ["2026-02-01", "2026-02-28"]}], "current_filters": [{"column": "Date", "operator": "date_range", "values": ["2026-03-01", "2026-03-31"]}]})
    contribution = tools.execute(business_frame, "calculate_contribution", {"dimension": "Region", "metric": "Revenue", "baseline_filters": [{"column": "Date", "operator": "date_range", "values": ["2026-02-01", "2026-02-28"]}], "current_filters": [{"column": "Date", "operator": "date_range", "values": ["2026-03-01", "2026-03-31"]}]})
    correlation = tools.execute(business_frame, "calculate_correlation", {"x": "Revenue", "y": "Units_Sold", "method": "pearson"})
    distribution = tools.execute(business_frame, "distribution_summary", {"column": "Revenue"})
    series = tools.execute(business_frame, "time_series_aggregate", {"date_column": "Date", "metric": "Revenue", "frequency": "monthly", "aggregation": "sum"})

    assert grouped.result == [{"Region": "North", "value": 310.0}, {"Region": "South", "value": 250.0}]
    assert len(filtered.result) == 3
    assert changed.result == {"previous_value": 220.0, "current_value": 160.0, "absolute_change": -60.0, "percentage_change": pytest.approx(-27.272727)}
    assert contribution.result["total_change"] == -60.0
    assert correlation.result["coefficient"] == pytest.approx(1.0)
    assert correlation.result["sample_size"] == 6
    assert distribution.result["median"] == 95.0
    assert [row["Revenue"] for row in series.result] == [180.0, 220.0, 160.0]
    pd.testing.assert_frame_equal(business_frame, original)


def test_percentage_change_handles_zero_and_tool_validation_rejects_unsafe_input() -> None:
    frame = pd.DataFrame({"period": ["before", "after"], "value": [0.0, 5.0], "label": ["a", "b"]})
    result = AnalyticsToolRegistry().execute(frame, "calculate_percentage_change", {"metric": "value", "previous_filters": [{"column": "period", "operator": "equals", "value": "before"}], "current_filters": [{"column": "period", "operator": "equals", "value": "after"}]})
    assert result.result["percentage_change"] is None
    assert "undefined" in result.warnings[-1]
    with pytest.raises(ToolValidationError):
        AnalyticsToolRegistry().execute(frame, "groupby_aggregate", {"group_by": ["missing"], "metric": "value", "aggregation": "sum"})
    with pytest.raises(ToolValidationError):
        AnalyticsToolRegistry().execute(frame, "distribution_summary", {"column": "label"})
    with pytest.raises(ToolValidationError):
        AnalyticsToolRegistry().execute(frame, "execute_sql", {"sql": "select *"})


@pytest.mark.parametrize(
    ("test_type", "columns", "group_column"),
    [
        ("pearson", ["x", "y"], None),
        ("spearman", ["x", "y"], None),
        ("independent_t_test", ["group", "x"], "group"),
        ("welch_t_test", ["group", "x"], "group"),
        ("mann_whitney_u", ["group", "x"], "group"),
        ("anova", ["multi_group", "x"], "multi_group"),
        ("chi_square", ["category_a", "category_b"], None),
    ],
)
def test_statistical_registry_returns_normalized_deterministic_results(test_type, columns, group_column) -> None:
    frame = pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 7, 8, 9, 10, 5, 6, 11, 12],
            "y": [2, 4, 6, 8, 14, 16, 18, 20, 10, 12, 22, 24],
            "group": ["A"] * 6 + ["B"] * 6,
            "multi_group": ["A"] * 4 + ["B"] * 4 + ["C"] * 4,
            "category_a": ["A", "A", "B", "B"] * 3,
            "category_b": ["X", "Y", "X", "Y", "X", "Y"] * 2,
        }
    )
    request = StatisticalValidationRequest(method_requested="deterministic validation", test_type=test_type, columns=columns, group_column=group_column, assumptions_to_check=["normality", "equal_variance"])
    result = StatisticalToolRegistry().execute(frame, request)
    assert result.method_used == test_type
    assert result.is_valid is True
    assert result.p_value is not None
    assert result.assumptions["significance_alpha"] == 0.05
    if test_type in {"independent_t_test", "welch_t_test"}:
        assert result.effect_size is not None
        assert result.confidence_interval is not None
    if test_type == "mann_whitney_u":
        assert result.effect_size is not None


def test_topological_order_respects_dependencies_then_priority() -> None:
    tasks = [
        SimpleNamespace(task_code="A3", depends_on=["A1"], priority=1),
        SimpleNamespace(task_code="A2", depends_on=[], priority=2),
        SimpleNamespace(task_code="A1", depends_on=[], priority=1),
    ]
    ordered = AnalysisTaskExecutionService._topological_tasks(tasks)
    assert [task.task_code for task in ordered] == ["A1", "A2", "A3"]


def test_numeric_grounding_accepts_result_values_and_rejects_invented_values() -> None:
    AnalystAgent._validate_numeric_grounding("Revenue changed by -20.0 from 100 to 80.", {"previous": 100, "current": 80, "change": -20.0})
    AnalystAgent._validate_numeric_grounding("The 95% confidence interval is available.", {"confidence_level": 0.95})
    with pytest.raises(NumericGroundingError):
        AnalystAgent._validate_numeric_grounding("Revenue changed by 17.5%.", {"percentage_change": 12.5})
    with pytest.raises(NumericGroundingError):
        AnalystAgent._validate_numeric_grounding("Revenue was 31000.", {"revenue": 310})


def test_main_response_is_conversational_and_does_not_expose_raw_evidence_json() -> None:
    response = AnalysisTaskExecutionService.format_response(
        [{"interpretation": "North generated 310.0 in revenue.", "result": {"North": 310.0}, "limitations": []}],
        [],
    )
    assert "North generated 310.0" in response
    assert "Deterministic result" not in response
    assert '{"North"' not in response


class MockStructuredLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def generate_structured(self, *, provider, messages, response_model):
        self.calls.append((provider, response_model.__name__, messages))
        content = self.responses[response_model]
        return LLMResult(provider=provider, model=f"{provider}-mock", content=content, usage=LLMUsage(total_tokens=3), latency_ms=2)

    async def generate_text(self, *, provider, messages):
        self.calls.append((provider, "text", messages))
        source = self.responses.get(EvidenceInterpretation) or self.responses.get(StatisticalInterpretation) or {"interpretation": "Deterministic result interpreted."}
        return LLMResult(provider=provider, model=f"{provider}-mock", content={"text": source["interpretation"]}, usage=LLMUsage(total_tokens=3), latency_ms=2)


@pytest.mark.anyio
async def test_mocked_analysis_agent_selects_tool_then_interprets_grounded_result(business_frame) -> None:
    llm = MockStructuredLLM(
        {
            AnalysisExecutionRequest: {"tool": "groupby_aggregate", "parameters": {"group_by": ["Region"], "metric": "Revenue", "aggregation": "sum"}, "interpretation_focus": "Rank regions."},
            EvidenceInterpretation: {"interpretation": "North generated 310.0 in revenue.", "limitations": ["Missing values would be ignored."]},
        }
    )
    result = await AnalystAgent(llm).run(provider="gemini", query="Which region generated the highest revenue?", task={"objective": "Rank regional revenue.", "analysis_type": "aggregation"}, verified_columns=list(business_frame.columns), profile_metadata={"row_count": 6, "columns": [{"name": name} for name in business_frame.columns]}, dataframe=business_frame, prior_evidence=[])
    assert [call[1] for call in llm.calls] == ["text"]
    assert all(call[0] == "gemini" for call in llm.calls)
    assert result.content["tool_result"]["result"][0] == {"Region": "North", "value": 310.0}


@pytest.mark.anyio
async def test_analysis_agent_uses_deterministic_time_series_fallback_when_llm_fails(business_frame) -> None:
    class FailingLLM:
        async def generate_text(self, **_kwargs):
            raise LLMProviderError("LLM_REQUEST_FAILED", "Provider unavailable.")

    result = await AnalystAgent(FailingLLM()).run(
        provider="gemini",
        query="Explain the monthly revenue trend.",
        task={
            "task_code": "T3",
            "objective": "Analyze monthly revenue performance.",
            "analysis_type": "time_series",
            "required_columns": ["Date", "Revenue"],
        },
        verified_columns=list(business_frame.columns),
        profile_metadata={"columns": [{"name": "Date", "inferred_type": "date"}, {"name": "Revenue", "inferred_type": "numeric"}]},
        dataframe=business_frame,
        prior_evidence=[],
    )

    assert result.content["selection"]["tool"] == "time_series_aggregate"
    assert result.content["selection"]["parameters"] == {"metric": "Revenue", "aggregation": "sum", "date_column": "Date", "frequency": "monthly"}
    assert [row["Revenue"] for row in result.content["tool_result"]["result"]] == [180.0, 220.0, 160.0]
    assert "come directly from the completed calculation" in result.content["interpretation"]["limitations"][0]
    assert "Revenue:" in result.content["interpretation"]["interpretation"]


@pytest.mark.anyio
async def test_analysis_agent_builds_time_series_parameters_without_llm_selection(business_frame) -> None:
    llm = MockStructuredLLM({
        AnalysisExecutionRequest: {
            "tool": "time_series_aggregate",
            "parameters": {"date_column": "Date", "frequency": "monthly", "aggregation": "sum"},
            "interpretation_focus": "Explain monthly performance.",
        },
        EvidenceInterpretation: {"interpretation": "The monthly revenue trend was calculated from verified rows.", "limitations": []},
    })

    result = await AnalystAgent(llm).run(
        provider="gemini",
        query="Analyze revenue performance across months.",
        task={"task_code": "TASK_003", "objective": "Explain monthly revenue trends.", "analysis_type": "time_series", "required_columns": ["Date", "Revenue"]},
        verified_columns=list(business_frame.columns),
        profile_metadata={"columns": [{"name": "Date", "inferred_type": "date"}, {"name": "Revenue", "inferred_type": "numeric"}]},
        dataframe=business_frame,
        prior_evidence=[],
    )

    assert result.content["selection"]["parameters"]["metric"] == "Revenue"
    assert result.content["selection"]["parameters"]["date_column"] == "Date"
    assert [call[1] for call in llm.calls] == ["text"]


@pytest.mark.anyio
async def test_mocked_statistical_agent_uses_same_provider_for_selection_and_interpretation(business_frame) -> None:
    llm = MockStructuredLLM(
        {
            StatisticalValidationRequest: {"method_requested": "correlation", "test_type": "pearson", "columns": ["Revenue", "Units_Sold"], "group_column": None, "assumptions_to_check": []},
            StatisticalInterpretation: {"interpretation": "The correlation is 1.0 across 6 observations; correlation does not establish causation."},
        }
    )
    result = await StatisticalValidatorAgent(llm).run(provider="groq", task={"objective": "Test association."}, verified_columns=list(business_frame.columns), dataframe=business_frame)
    assert [call[1] for call in llm.calls] == ["text"]
    assert all(call[0] == "groq" for call in llm.calls)
    assert result.content["result"]["is_valid"] is True


def test_stage8_gemini_selection_schema_has_explicit_object_properties() -> None:
    schema = GeminiProvider._build_gemini_schema(AnalysisExecutionRequest)

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


@pytest.mark.anyio
async def test_failed_dependency_is_skipped_and_not_executed() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = AnalysisTaskExecutionService(session, SimpleNamespace())
    task_a = SimpleNamespace(id=uuid4(), task_code="A1", objective="Fail safely.", analysis_type="aggregation", method="sum", required_columns=["Revenue"], depends_on=[], priority=1, status="pending")
    task_b = SimpleNamespace(id=uuid4(), task_code="A2", objective="Dependent.", analysis_type="comparison", method="compare", required_columns=["Revenue"], depends_on=["A1"], priority=2, status="pending")
    session.get = AsyncMock(side_effect=lambda _model, task_id: task_a if task_id == task_a.id else task_b if task_id == task_b.id else None)
    plan = SimpleNamespace(tasks=[task_a, task_b])
    service.plan_service = SimpleNamespace(
        persist_validated=AsyncMock(),
        plans=SimpleNamespace(get_by_analysis_run_id=AsyncMock(return_value=plan)),
        tasks=SimpleNamespace(update_status=AsyncMock(side_effect=lambda task, status, reason=None: (setattr(task, "status", status), setattr(task, "status_reason", reason)))),
    )
    service.files = SimpleNamespace(download=AsyncMock(return_value=b"mocked"))
    service.loader = SimpleNamespace(load=lambda *_: SimpleNamespace(dataframe=pd.DataFrame({"Revenue": [1, 2]})))
    service.analyst = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("mocked failure")))
    service.evidence_service = SimpleNamespace(create=AsyncMock())
    plan_output = SimpleNamespace(limitations=[])

    with pytest.raises(TaskExecutionFailure, match="ANALYSIS_TOOL_EXECUTION_FAILED"):
        await service.execute_analysis(run=SimpleNamespace(id=uuid4(), llm_provider="gemini", query="bounded"), dataset=SimpleNamespace(file_type="csv"), plan_output=plan_output, profile={"columns": [{"name": "Revenue"}]}, run_agent=lambda *args: args[2]())

    assert task_a.status == "failed"
    assert task_b.status == "skipped"
    assert "dependency" in task_b.status_reason
    assert service.analyst.run.await_count == 1
    service.evidence_service.create.assert_not_awaited()
