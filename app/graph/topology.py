"""Shared execution edges and documented state contracts (no business data)."""
EDGES = [
    ("__start__", "load_context"), ("load_context", "supervisor"),
    ("profile_interpreter", "planner"), ("planner", "execute_analysis"),
    ("execute_analysis", "statistical_validation"), ("statistical_validation", "generate_claims"),
    ("generate_claims", "critic"), ("critic", "visualization"),
    ("visualization", "report"), ("report", "prepare_response"), ("prepare_response", "__end__"),
]
ROUTES = {"profile_interpreter": "profile_interpreter", "prepare_response": "prepare_response"}
# State fields identify data contracts, not direct peer-to-peer agent messages.
CONTRACTS = {
    "load_context": (["user_query", "dataset_profile", "conversation_context"], []),
    "supervisor": (["user_query", "dataset_profile", "conversation_context"], ["supervisor_decision"]),
    "profile_interpreter": (["user_query", "dataset_profile", "supervisor_decision"], ["profile_interpretation"]),
    "planner": (["user_query", "dataset_profile", "supervisor_decision", "profile_interpretation"], ["analysis_plan"]),
    "execute_analysis": (["analysis_plan", "dataset_profile"], ["evidence"]),
    "statistical_validation": (["analysis_plan", "dataset_profile", "evidence"], ["statistical_validations"]),
    "generate_claims": (["evidence"], ["claims"]),
    "critic": (["claims", "evidence", "statistical_validations", "dataset_profile"], ["claim_reviews", "accepted_claims"]),
    "visualization": (["accepted_claims", "evidence", "dataset_profile"], ["chart_specs"]),
    "report": (["accepted_claims", "evidence", "statistical_validations", "dataset_profile"], ["final_report"]),
    "prepare_response": (["supervisor_decision", "final_report", "evidence", "statistical_validations", "analysis_plan"], ["assistant_message"]),
}
PRODUCERS = {field: stage for stage, (_, outputs) in CONTRACTS.items() for field in outputs}
