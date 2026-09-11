from app.core.tracing import traced
from app.graph.topology import EDGES, ROUTES

from langgraph.graph import StateGraph

from app.agents import PlannerAgent, ProfileInterpreterAgent, SupervisorAgent
from app.graph.nodes import AgentRunner, StateExecutor, critic, execute_analysis, generate_claims, load_context, planner, prepare_response, profile_interpreter, report, route_after_supervisor, statistical_validation, supervisor, visualization
from app.graph.state import AnalysisState
from app.services.llm.llm_service import LLMService


class AnalysisWorkflow:
    def __init__(self, llm_service: LLMService, run_agent: AgentRunner, analysis_executor: StateExecutor | None = None, statistics_executor: StateExecutor | None = None, claim_executor: StateExecutor | None = None, critic_executor: StateExecutor | None = None, visualization_executor: StateExecutor | None = None, report_executor: StateExecutor | None = None) -> None:
        self.supervisor_agent = SupervisorAgent(llm_service)
        self.profile_interpreter_agent = ProfileInterpreterAgent(llm_service)
        self.planner_agent = PlannerAgent(llm_service)
        self.run_agent = run_agent
        self.analysis_executor = analysis_executor or self._empty_analysis
        self.statistics_executor = statistics_executor or self._empty_statistics
        self.claim_executor = claim_executor or self._empty_claims
        self.critic_executor = critic_executor or self._empty_reviews
        self.visualization_executor = visualization_executor or self._empty_charts
        self.report_executor = report_executor or self._empty_report
        self.graph = self._build()

    def _build(self):
        builder = StateGraph(AnalysisState)
        builder.add_node("load_context", load_context)

        async def run_supervisor(state: AnalysisState) -> dict[str, object]:
            return await supervisor(state, self.supervisor_agent, self.run_agent)

        async def run_profile_interpreter(state: AnalysisState) -> dict[str, object]:
            return await profile_interpreter(state, self.profile_interpreter_agent, self.run_agent)

        async def run_planner(state: AnalysisState) -> dict[str, object]:
            return await planner(state, self.planner_agent, self.run_agent)

        async def run_analysis(state: AnalysisState) -> dict[str, object]:
            return await execute_analysis(state, self.analysis_executor)

        async def run_statistics(state: AnalysisState) -> dict[str, object]:
            return await statistical_validation(state, self.statistics_executor)

        async def run_claims(state: AnalysisState) -> dict[str, object]:
            return await generate_claims(state, self.claim_executor)

        async def run_critic(state: AnalysisState) -> dict[str, object]:
            return await critic(state, self.critic_executor)

        async def run_visualization(state: AnalysisState) -> dict[str, object]:
            return await visualization(state, self.visualization_executor)

        async def run_report(state: AnalysisState) -> dict[str, object]:
            return await report(state, self.report_executor)

        builder.add_node("supervisor", run_supervisor)
        builder.add_node("profile_interpreter", run_profile_interpreter)
        builder.add_node("planner", run_planner)
        builder.add_node("execute_analysis", run_analysis)
        builder.add_node("statistical_validation", run_statistics)
        builder.add_node("generate_claims", run_claims)
        builder.add_node("critic", run_critic)
        builder.add_node("visualization", run_visualization)
        builder.add_node("report", run_report)
        builder.add_node("prepare_response", prepare_response)
        for source, target in EDGES:
            builder.add_edge(source, target)
        builder.add_conditional_edges("supervisor", route_after_supervisor, ROUTES)
        return builder.compile()

    @traced("workflow")
    async def execute(self, state: AnalysisState) -> AnalysisState:
        return await self.graph.ainvoke(state)

    @staticmethod
    async def _empty_analysis(state: AnalysisState) -> dict[str, object]:
        return {"evidence": []}

    @staticmethod
    async def _empty_statistics(state: AnalysisState) -> dict[str, object]:
        return {"statistical_validations": []}

    @staticmethod
    async def _empty_claims(state: AnalysisState) -> dict[str, object]:
        return {"claims": []}

    @staticmethod
    async def _empty_reviews(state: AnalysisState) -> dict[str, object]:
        return {"claim_reviews": [], "accepted_claims": []}

    @staticmethod
    async def _empty_charts(state: AnalysisState) -> dict[str, object]:
        return {"chart_specs": []}

    @staticmethod
    async def _empty_report(state: AnalysisState) -> dict[str, object]:
        return {"final_report": None}
