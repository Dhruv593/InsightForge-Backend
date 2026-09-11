from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.graph.workflow import AnalysisWorkflow
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.llm import LLMResult, LLMUsage
from app.schemas.profile_interpretation import ProfileInterpretation
from app.schemas.supervisor import SupervisorDecision
from app.services.analysis_plan_service import AgentSemanticValidationError, AnalysisPlanService
from app.services.analysis_execution_service import AnalysisExecutionService
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.llm_service import LLMService

pytestmark = pytest.mark.anyio

COLUMNS = {"Date", "Region", "Product", "Revenue", "Units_Sold"}

SUPERVISOR = {
    "query_type": "diagnostic",
    "objective": "Plan an investigation of the revenue change.",
    "target_metrics": ["Revenue"],
    "relevant_dimensions": ["Region", "Product"],
    "requires_statistics": True,
    "requires_visualization": True,
    "can_answer_with_available_data": True,
    "missing_requirements": [],
}
PROFILE = {
    "relevant_columns": [
        {"name": "Revenue", "role": "metric", "inferred_type": "numeric", "relevance_reason": "Requested metric."},
        {"name": "Date", "role": "date", "inferred_type": "datetime", "relevance_reason": "Required period."},
        {"name": "Region", "role": "dimension", "inferred_type": "categorical", "relevance_reason": "Useful decomposition."},
    ],
    "usable_date_columns": ["Date"],
    "data_quality_constraints": [],
    "excluded_columns": [],
    "analysis_warnings": [],
}
PLAN = {
    "question_type": "diagnostic",
    "objective": "Identify contributors to the revenue change.",
    "target_metric": "Revenue",
    "analysis_strategy": "Compare periods and decompose the change using verified dimensions.",
    "requires_statistics": True,
    "requires_visualization": True,
    "tasks": [
        {"task_code": "A1", "objective": "Compare revenue over time.", "analysis_type": "comparison", "required_columns": ["Date", "Revenue"], "method": "period comparison", "priority": 1, "depends_on": []},
        {"task_code": "A2", "objective": "Break down the change by region.", "analysis_type": "segmentation", "required_columns": ["Date", "Region", "Revenue"], "method": "regional decomposition", "priority": 2, "depends_on": ["A1"]},
    ],
    "completion_criteria": ["Contributing dimensions are ranked."],
    "limitations": ["Observational relationships are not causal."],
}


class SchemaProvider(BaseLLMProvider):
    def __init__(self, provider_name: str, unsupported: bool = False) -> None:
        super().__init__(api_key="test", model=f"{provider_name}-test", timeout_seconds=1)
        self.provider_name = provider_name
        self.unsupported = unsupported
        self.calls: list[str] = []

    async def generate_structured(self, *, messages, response_model) -> LLMResult:
        self.calls.append(response_model.__name__)
        if response_model is SupervisorDecision:
            content = deepcopy(SUPERVISOR)
            if self.unsupported:
                content.update(query_type="unsupported", target_metrics=[], relevant_dimensions=[], can_answer_with_available_data=False, missing_requirements=["Competitor pricing data is unavailable."])
        elif response_model is ProfileInterpretation:
            content = deepcopy(PROFILE)
        else:
            content = deepcopy(PLAN)
        return LLMResult(provider=self.provider_name, model=self.model_name, content=content, usage=LLMUsage(total_tokens=10), latency_ms=4)


def settings():
    return SimpleNamespace(gemini_api_key=None, gemini_model=None, groq_api_key=None, groq_model=None, llm_request_timeout_seconds=1)


def state(provider: str):
    return {
        "analysis_run_id": "run", "user_id": "user", "dataset_id": "dataset",
        "conversation_id": "conversation", "user_query": "Why did revenue decrease?",
        "llm_provider": provider,
        "dataset_profile": {"file_name": "business.csv", "row_count": 31, "column_count": 5, "columns": [{"name": name, "inferred_type": "unknown", "missing_percentage": 0} for name in sorted(COLUMNS)], "quality_issues": []},
        "conversation_context": [], "supervisor_decision": None,
        "profile_interpretation": None, "analysis_plan": None,
        "current_node": None, "assistant_message": None,
        "error_code": None, "error_message": None,
    }


@pytest.mark.parametrize("provider_name", ["gemini", "groq"])
async def test_all_three_agents_use_the_persisted_provider(provider_name: str) -> None:
    provider = SchemaProvider(provider_name)
    service = LLMService(settings=settings(), providers={provider_name: provider})
    logged: list[tuple[str, str]] = []

    async def runner(agent_name, input_json, invoke):
        result = await invoke()
        logged.append((agent_name, result.provider))
        return result

    result = await AnalysisWorkflow(service, runner).execute(state(provider_name))
    assert logged == [("supervisor", provider_name), ("profile_interpreter", provider_name), ("planner", provider_name)]
    assert provider.calls == ["SupervisorDecision", "AnalysisPlanOutput"]
    assert "calculations have not been executed" in result["assistant_message"]


async def test_unsupported_supervisor_skips_downstream_agents() -> None:
    provider = SchemaProvider("gemini", unsupported=True)
    service = LLMService(settings=settings(), providers={"gemini": provider})
    logged = []

    async def runner(agent_name, input_json, invoke):
        logged.append(agent_name)
        return await invoke()

    result = await AnalysisWorkflow(service, runner).execute(state("gemini"))
    assert logged == ["supervisor"]
    assert result["analysis_plan"] is None
    assert "Competitor pricing data is unavailable" in result["assistant_message"]


def test_supervisor_and_profile_interpreter_reject_invented_columns() -> None:
    bad_supervisor = SupervisorDecision.model_validate({**SUPERVISOR, "target_metrics": ["Profit"]})
    with pytest.raises(AgentSemanticValidationError):
        AnalysisPlanService.validate_supervisor(bad_supervisor, COLUMNS)
    bad_profile = ProfileInterpretation.model_validate({**PROFILE, "excluded_columns": ["Customer_Age"]})
    with pytest.raises(AgentSemanticValidationError):
        AnalysisPlanService.validate_profile_interpretation(bad_profile, COLUMNS)


@pytest.mark.parametrize("mutation", ["invented", "duplicate", "unknown", "self", "cycle", "limit"])
def test_invalid_plans_are_rejected(mutation: str) -> None:
    value = deepcopy(PLAN)
    if mutation == "invented": value["tasks"][0]["required_columns"] = ["Profit"]
    elif mutation == "duplicate": value["tasks"][1]["task_code"] = "A1"
    elif mutation == "unknown": value["tasks"][1]["depends_on"] = ["A9"]
    elif mutation == "self": value["tasks"][0]["depends_on"] = ["A1"]
    elif mutation == "cycle":
        value["tasks"][0]["depends_on"] = ["A2"]
        value["tasks"][1]["depends_on"] = ["A1"]
    else:
        value["tasks"] = [
            {**deepcopy(PLAN["tasks"][0]), "task_code": f"A{i}"}
            for i in range(1, 12)
        ]
    with pytest.raises(AgentSemanticValidationError):
        AnalysisPlanService.validate_plan(AnalysisPlanOutput.model_validate(value), COLUMNS)


async def test_valid_plan_and_tasks_are_staged_without_committing() -> None:
    session = SimpleNamespace()
    service = AnalysisPlanService(session)
    service.plans = SimpleNamespace(create=AsyncMock(side_effect=lambda plan: plan))
    service.tasks = SimpleNamespace(create_many=AsyncMock(side_effect=lambda tasks: tasks))
    output = AnalysisPlanService.validate_plan(AnalysisPlanOutput.model_validate(PLAN), COLUMNS)
    plan = await service.persist_validated(SimpleNamespace(), output, COLUMNS)
    assert plan.status == "validated"
    service.plans.create.assert_awaited_once()
    staged_tasks = service.tasks.create_many.await_args.args[0]
    assert [task.task_code for task in staged_tasks] == ["A1", "A2"]
    assert not hasattr(session, "commit")


@pytest.mark.parametrize(
    ("failure_agent", "expected_calls"),
    [
        ("supervisor", ["supervisor"]),
        ("profile_interpreter", ["supervisor", "profile_interpreter"]),
        ("planner", ["supervisor", "profile_interpreter", "planner"]),
    ],
)
async def test_agent_failure_stops_downstream_graph(failure_agent, expected_calls) -> None:
    provider = SchemaProvider("gemini")
    service = LLMService(settings=settings(), providers={"gemini": provider})
    calls = []

    async def runner(agent_name, input_json, invoke):
        calls.append(agent_name)
        if agent_name == failure_agent:
            raise RuntimeError("mocked agent failure")
        return await invoke()

    with pytest.raises(RuntimeError, match="mocked agent failure"):
        await AnalysisWorkflow(service, runner).execute(state("gemini"))
    assert calls == expected_calls


async def test_task_insertion_failure_does_not_commit_partial_plan() -> None:
    session = SimpleNamespace()
    service = AnalysisPlanService(session)
    service.plans = SimpleNamespace(create=AsyncMock(side_effect=lambda plan: plan))
    service.tasks = SimpleNamespace(
        create_many=AsyncMock(side_effect=SQLAlchemyError("mocked insertion failure"))
    )
    output = AnalysisPlanOutput.model_validate(PLAN)
    from app.core.exceptions import AnalysisPlanPersistenceError

    with pytest.raises(AnalysisPlanPersistenceError):
        await service.persist_validated(SimpleNamespace(), output, COLUMNS)
    assert not hasattr(session, "commit")


async def test_each_agent_invocation_creates_and_completes_a_separate_log() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    service = AnalysisExecutionService(session, llm_service=SimpleNamespace())
    created = []

    async def start(**values):
        record = SimpleNamespace(id=uuid4(), **values)
        created.append(record)
        return record

    service.agent_run_service = SimpleNamespace(start=AsyncMock(side_effect=start))
    service.agent_runs = SimpleNamespace(
        mark_completed=AsyncMock(), mark_failed=AsyncMock(), get_by_id=AsyncMock()
    )
    run = SimpleNamespace(id=uuid4(), llm_provider="groq")

    async def invoke():
        return LLMResult(
            provider="groq", model="groq-test", content={"ok": True},
            usage=LLMUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3),
            latency_ms=5,
        )

    for agent_name in ("supervisor", "profile_interpreter", "planner"):
        await service._run_agent(
            run, agent_name, "groq-test", {"query": "bounded"}, invoke
        )

    assert [record.agent_name for record in created] == [
        "supervisor", "profile_interpreter", "planner"
    ]
    assert all(record.provider == "groq" for record in created)
    assert service.agent_runs.mark_completed.await_count == 3
    assert session.commit.await_count == 6


@pytest.mark.parametrize(
    "response_model",
    [SupervisorDecision, ProfileInterpretation, AnalysisPlanOutput],
)
def test_stage7_gemini_schemas_are_flat_and_use_supported_keywords(response_model) -> None:
    schema = GeminiProvider._build_gemini_schema(response_model)
    forbidden = {
        "$defs", "$ref", "pattern", "title", "default", "additionalProperties",
        "minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum",
    }

    def inspect(value):
        if isinstance(value, dict):
            assert not (set(value) & forbidden)
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    inspect(schema)
    assert schema["type"] == "object"
    assert set(schema["required"]) == set(schema["properties"])

    if response_model is AnalysisPlanOutput:
        task_schema = schema["properties"]["tasks"]["items"]
        assert task_schema["type"] == "object"
        assert task_schema["properties"]["analysis_type"]["enum"] == [
            "aggregation", "comparison", "segmentation", "correlation",
            "statistical_test", "regression", "time_series", "distribution",
            "data_quality",
        ]
