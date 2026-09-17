"""Read-only Studio topology. Never connect this development server to user data."""
from langgraph.graph import StateGraph
from app.graph.state import AnalysisState
from app.graph.topology import CONTRACTS, EDGES, ROUTES


async def read_only(state: AnalysisState):
    raise RuntimeError("Topology viewer only. Run analyses through authenticated Tatparya and inspect their LangSmith traces.")


def build_graph():
    builder = StateGraph(AnalysisState)
    for stage in CONTRACTS:
        reads, writes = CONTRACTS[stage]
        builder.add_node(stage, read_only, metadata={"reads": reads, "writes": writes, "mode": "topology-only"})
    for source, target in EDGES:
        builder.add_edge(source, target)
    builder.add_conditional_edges("supervisor", lambda state: "prepare_response", ROUTES)
    return builder.compile()


graph = build_graph()
