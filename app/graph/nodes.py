from collections.abc import Awaitable, Callable
from app.core.tracing import traced, trace_event
from typing import Any

from app.agents.planner import PlannerAgent
from app.agents.profile_interpreter import ProfileInterpreterAgent
from app.agents.supervisor import SupervisorAgent
from app.core.analysis_constants import PLANNER_AGENT_NAME, PROFILE_INTERPRETER_AGENT_NAME, SUPERVISOR_AGENT_NAME
from app.graph.state import AnalysisState
from app.schemas.analysis_plan import AnalysisPlanOutput
from app.schemas.llm import LLMResult
from app.schemas.profile_interpretation import ProfileInterpretation
from app.schemas.supervisor import SupervisorDecision

AgentRunner = Callable[[str, dict[str, Any], Callable[[], Awaitable[LLMResult]]], Awaitable[LLMResult]]
StateExecutor = Callable[[AnalysisState], Awaitable[dict[str, object]]]


@traced("stage.load_context")
async def load_context(state: AnalysisState) -> dict[str, object]:
    if not state.get("dataset_profile"):
        raise ValueError("Dataset profile context is required.")
    if not state.get("user_query", "").strip():
        raise ValueError("User query context is required.")
    return {"current_node": "load_context"}


@traced("stage.supervisor")
async def supervisor(state: AnalysisState, agent: SupervisorAgent, run_agent: AgentRunner) -> dict[str, object]:
    profile = state["dataset_profile"] or {}
    agent_input = {
        "query": state["user_query"],
        "dataset_file_name": profile.get("file_name"),
        "row_count": profile.get("row_count"),
        "column_count": profile.get("column_count"),
        "dataset_columns": [column["name"] for column in profile.get("columns", [])],
    }

    async def invoke() -> LLMResult:
        return await agent.run(provider=state["llm_provider"], query=state["user_query"], dataset_context=profile, conversation_context=state["conversation_context"])

    result = await run_agent(SUPERVISOR_AGENT_NAME, agent_input, invoke)
    return {"current_node": SUPERVISOR_AGENT_NAME, "supervisor_decision": result.content}


def route_after_supervisor(state: AnalysisState) -> str:
    decision = SupervisorDecision.model_validate(state.get("supervisor_decision"))
    return "profile_interpreter" if decision.can_answer_with_available_data else "prepare_response"


@traced("stage.profile_interpreter")
async def profile_interpreter(state: AnalysisState, agent: ProfileInterpreterAgent, run_agent: AgentRunner) -> dict[str, object]:
    decision = SupervisorDecision.model_validate(state.get("supervisor_decision"))
    profile = state["dataset_profile"] or {}
    agent_input = {"query": state["user_query"], "supervisor_decision": decision.model_dump(mode="json")}

    async def invoke() -> LLMResult:
        return await agent.run(provider=state["llm_provider"], query=state["user_query"], supervisor_decision=decision, dataset_context=profile)

    result = await run_agent(PROFILE_INTERPRETER_AGENT_NAME, agent_input, invoke)
    return {"current_node": PROFILE_INTERPRETER_AGENT_NAME, "profile_interpretation": result.content}


@traced("stage.planner")
async def planner(state: AnalysisState, agent: PlannerAgent, run_agent: AgentRunner) -> dict[str, object]:
    decision = SupervisorDecision.model_validate(state.get("supervisor_decision"))
    interpretation = ProfileInterpretation.model_validate(state.get("profile_interpretation"))
    profile = state["dataset_profile"] or {}
    verified_columns = [column["name"] for column in profile.get("columns", [])]
    agent_input = {
        "query": state["user_query"],
        "supervisor_decision": decision.model_dump(mode="json"),
        "profile_interpretation": interpretation.model_dump(mode="json"),
    }

    async def invoke() -> LLMResult:
        return await agent.run(provider=state["llm_provider"], query=state["user_query"], supervisor_decision=decision, profile_interpretation=interpretation, verified_columns=verified_columns)

    result = await run_agent(PLANNER_AGENT_NAME, agent_input, invoke)
    return {"current_node": PLANNER_AGENT_NAME, "analysis_plan": result.content}


@traced("stage.execute_analysis")
async def execute_analysis(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    result = await executor(state)
    return {"current_node": "execute_analysis", **result}


@traced("stage.statistical_validation")
async def statistical_validation(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    result = await executor(state)
    return {"current_node": "statistical_validation", **result}


@traced("stage.generate_claims")
async def generate_claims(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    return {"current_node": "generate_claims", **await executor(state)}


@traced("stage.critic")
async def critic(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    return {"current_node": "critic", **await executor(state)}


@traced("stage.visualization")
async def visualization(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    return {"current_node": "visualization", **await executor(state)}


@traced("stage.report")
async def report(state: AnalysisState, executor: StateExecutor) -> dict[str, object]:
    return {"current_node": "report", **await executor(state)}


@traced("stage.prepare_response")
async def prepare_response(state: AnalysisState) -> dict[str, object]:
    decision = SupervisorDecision.model_validate(state.get("supervisor_decision"))
    if not decision.can_answer_with_available_data:
        await trace_event("unsupported_request", outcome="unsupported")
        return {
            "current_node": "prepare_response",
            "assistant_message": ("This request cannot be supported with the available dataset. " + " ".join(_plain_text(item) for item in decision.missing_requirements)).strip(),
        }
    if state.get("final_report"):
        from app.services.analysis_output_service import AnalysisOutputService
        return {"current_node": "prepare_response", "assistant_message": AnalysisOutputService.format_report(state["final_report"])}
    if state.get("evidence"):
        from app.services.analysis_task_execution_service import AnalysisTaskExecutionService
        return {
            "current_node": "prepare_response",
            "assistant_message": AnalysisTaskExecutionService.format_response(
                state["evidence"] or [], state.get("statistical_validations") or []
            ),
        }
    plan = AnalysisPlanOutput.model_validate(state.get("analysis_plan"))
    task_lines = "\n".join(f"{index}. {_plain_text(task.objective)}" for index, task in enumerate(plan.tasks, start=1))
    limitations = ""
    if plan.limitations:
        limitations = "\n\nLimitations:\n" + "\n".join(f"- {_plain_text(item)}" for item in plan.limitations)
    return {
        "current_node": "prepare_response",
        "assistant_message": f"I can analyze this using the available dataset.\n\nPlanned analysis:\n{task_lines}{limitations}\n\nThe analytical calculations have not been executed yet.",
    }


def _plain_text(value: str) -> str:
    return value.replace("\\_", "_").replace("\\*", "*").replace("\\#", "#")
