"""Opt-in, metadata-only tracing. Never serialize ORM objects or raw prompts."""
import asyncio
import inspect
import logging
import re
from contextvars import ContextVar
from functools import lru_cache, wraps
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_parent = ContextVar("insightforge_trace_parent", default=None)
_outcome = ContextVar("insightforge_trace_outcome", default=None)


def _details_enabled():
    settings = get_settings()
    return getattr(settings, "langsmith_detail_mode", False) and settings.app_env == "development"


def _redact(value, depth=0):
    """Bounded development-only previews; use synthetic data, not production data."""
    if depth > 4:
        return "[depth limit]"
    if isinstance(value, dict):
        return {str(k)[:60]: "[redacted]" if re.search(r"password|secret|token|key|email|authorization|cookie|rows|records|dataframe|conversation", str(k), re.I)
                else _redact(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value[:3]]
    if isinstance(value, str):
        value = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|Bearer\s+\S+|\b[A-Za-z0-9_-]{32,}\b", "[redacted]", value)
        return value[:300]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _shape(value)


def _summary(value):
    from app.schemas.llm import LLMResult
    if isinstance(value, LLMResult):
        value = value.content
    summary = _shape(value)
    if isinstance(value, dict):
        from app.graph.topology import CONTRACTS, PRODUCERS
        fields = set(PRODUCERS) | {"tasks", "columns", "row_count", "column_count", "can_answer_with_available_data"}
        summary["fields"] = {key: _shape(value[key]) for key in sorted(fields & value.keys())}
        if value.get("current_node") in CONTRACTS:
            summary["stage"] = value["current_node"]
        if isinstance(value.get("can_answer_with_available_data"), bool):
            summary["can_answer_with_available_data"] = value["can_answer_with_available_data"]
    return summary


async def trace_event(event, *, error_code=None, attempt=None, outcome=None):
    """Only static event names and machine-readable codes; never exception messages."""
    run = _parent.get()
    if run is None:
        return
    context = _outcome.get()
    if outcome and context is not None:
        priority = {"completed": 0, "completed_with_fallback": 1, "unsupported": 2, "partial": 3, "recovered_partial": 4}
        if priority.get(outcome, 0) >= priority.get(context["outcome"], 0):
            context["outcome"] = outcome
    from datetime import datetime, timezone
    metadata = {}
    if isinstance(error_code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", error_code):
        metadata["error_code"] = error_code
    if isinstance(attempt, int):
        metadata["attempt"] = attempt
    await _safe(lambda: run.events.append({"name": event, "time": datetime.now(timezone.utc).isoformat(), "kwargs": metadata}))


@lru_cache(maxsize=1)
def _client():
    settings = get_settings()
    if not settings.langsmith_enabled:
        return None
    key = settings.langsmith_api_key
    if not key or not key.get_secret_value().strip():
        logger.warning("LangSmith tracing disabled: missing API key")
        return None
    from langsmith import Client
    return Client(api_key=key.get_secret_value(), api_url=settings.langsmith_endpoint,
                  auto_batch_tracing=True, timeout_ms=1500, omit_traced_runtime_info=True)


def _shape(value):
    # Contents, dict keys (which may be column names), IDs, and text are excluded.
    if isinstance(value, (list, tuple, dict)):
        return {"type": type(value).__name__, "count": len(value)}
    return {"type": type(value).__name__}


async def _safe(operation):
    try:
        # SDK enqueue/transport never runs on the request event loop.
        return await asyncio.wait_for(asyncio.to_thread(operation), timeout=2)
    except Exception:
        logger.warning("LangSmith tracing operation unavailable; continuing analysis")
        return None


def traced(name, run_type="chain"):
    """Keep application exceptions unchanged; never retry the wrapped operation."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        async def wrapped(*args, **kwargs):
            def start():
                client = _client()
                if client is None:
                    return None
                from langsmith.run_trees import RunTree
                arguments = signature.bind(*args, **kwargs).arguments
                metadata = {"privacy": "redacted-development-preview" if _details_enabled() else "safe-summaries"}
                run_id = arguments.get("analysis_run_id") or arguments.get("run_id")
                if isinstance(run_id, UUID):
                    metadata["analysis_run_id"] = str(run_id)
                agent = arguments.get("agent_name")
                # Only the fixed agent prefix, never arbitrary task descriptions.
                label = name
                if isinstance(agent, str):
                    prefix = agent.split(":")[0]
                    if prefix in {"supervisor", "planner", "profile_interpreter", "analyst", "critic", "visualization", "report", "claim_generator", "statistical_validator"}:
                        label = prefix
                instance = arguments.get("self")
                provider = getattr(instance, "provider_name", None)
                if provider in {"gemini", "groq"}:
                    metadata["ls_provider"] = provider
                    metadata["ls_model_name"] = instance.model_name
                inputs = {key: _summary(value) for key, value in arguments.items() if key not in {"self", "user", "invoke", "run_agent"}}
                from app.graph.topology import CONTRACTS, PRODUCERS
                stage = name.removeprefix("stage.")
                if stage in CONTRACTS:
                    reads, writes = CONTRACTS[stage]
                    state = arguments.get("state", {})
                    metadata["stage"] = stage
                    inputs["handoffs"] = [{"field": field, "from": PRODUCERS.get(field, "request_context"),
                        "to": stage, "available": state.get(field) is not None,
                        "summary": _summary(state.get(field))} for field in reads]
                    metadata["produces"] = writes
                    metadata["handoff_kind"] = "shared-state contract, not direct messages"
                if _details_enabled():
                    inputs["development_preview"] = {key: _redact(arguments[key]) for key in ("input_json", "state") if key in arguments}
                parent = _parent.get()
                if parent:
                    run = parent.create_child(name=label, run_type=run_type, inputs=inputs, extra={"metadata": metadata})
                else:
                    run = RunTree(name=label, run_type=run_type, inputs=inputs, extra={"metadata": metadata},
                                  project_name=get_settings().langsmith_project, ls_client=client)
                run.post()
                return run

            # No SDK initialization, tasks or serialization at all when disabled.
            if not get_settings().langsmith_enabled:
                return await function(*args, **kwargs)
            run = await _safe(start)
            token = _parent.set(run or _parent.get())
            root_token = None
            if name == "analysis.request":
                root_token = _outcome.set({"outcome": "completed"})
            try:
                result = await function(*args, **kwargs)
            except BaseException as exc:
                if run:
                    error_type = type(exc).__name__
                    await _safe(lambda: _finish(run, error=error_type))
                raise
            else:
                if run:
                    await _safe(lambda: _finish(run, result=result, detailed=_details_enabled(), outcome=(_outcome.get() or {}).get("outcome") if name == "analysis.request" else None))
                return result
            finally:
                _parent.reset(token)
                if root_token is not None:
                    _outcome.reset(root_token)
        return wrapped
    return decorate


def _finish(run, result=None, error=None, outcome=None, detailed=False):
    outputs = {"result": _summary(result)}
    if outcome:
        outputs["analysis_outcome"] = outcome
    # LLM token counts are safe; model response content is deliberately omitted.
    from app.schemas.llm import LLMResult
    if detailed:
        outputs["development_preview"] = _redact(result.content if isinstance(result, LLMResult) else result)
    if isinstance(result, LLMResult):
        usage = result.usage
        outputs["usage_metadata"] = {key: value for key, value in {
            "input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }.items() if value is not None}
    run.end(outputs=outputs, error=error)
    run.patch()
