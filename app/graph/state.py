from typing import Any, Literal, TypedDict


class AnalysisState(TypedDict):
    analysis_run_id: str
    user_id: str
    dataset_id: str
    conversation_id: str
    user_query: str
    llm_provider: Literal["gemini", "groq", "openai", "anthropic"]
    dataset_profile: dict[str, Any] | None
    conversation_context: list[dict[str, str]]
    supervisor_decision: dict[str, Any] | None
    profile_interpretation: dict[str, Any] | None
    analysis_plan: dict[str, Any] | None
    evidence: list[dict[str, Any]] | None
    statistical_validations: list[dict[str, Any]] | None
    claims: list[dict[str, Any]] | None
    claim_reviews: list[dict[str, Any]] | None
    accepted_claims: list[dict[str, Any]] | None
    chart_specs: list[dict[str, Any]] | None
    final_report: dict[str, Any] | None
    current_node: str | None
    assistant_message: str | None
    error_code: str | None
    error_message: str | None
