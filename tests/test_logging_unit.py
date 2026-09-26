import json
import logging
import sys

from app.core.logging_config import (
    JsonLogFormatter,
    LogContextFilter,
    bind_log_context,
    reset_log_context,
    update_log_context,
)


def _record(message="Completed request", *, extra=None, exc_info=None):
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg=message,
        args=(),
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


def test_json_logs_include_async_correlation_context_and_event():
    token = bind_log_context(request_id="request-1", analysis_run_id="run-1")
    try:
        update_log_context(user_id="user-1", dataset_id="dataset-1")
        record = _record(extra={"event": "analysis.completed", "duration_ms": 42.5})
        assert LogContextFilter(app_name="Tatparya API", environment="test").filter(record)
        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        reset_log_context(token)

    assert payload["event"] == "analysis.completed"
    assert payload["service"] == "Tatparya API"
    assert payload["environment"] == "test"
    assert payload["request_id"] == "request-1"
    assert payload["analysis_run_id"] == "run-1"
    assert payload["user_id"] == "user-1"
    assert payload["dataset_id"] == "dataset-1"
    assert payload["duration_ms"] == 42.5
    assert payload["timestamp"].endswith("Z")


def test_json_exception_keeps_safe_frames_and_redacts_message_values():
    try:
        raise RuntimeError("token=private-value")
    except RuntimeError:
        record = _record("Provider failed token=private-value", exc_info=sys.exc_info())

    LogContextFilter(app_name="Tatparya API", environment="test").filter(record)
    payload = json.loads(JsonLogFormatter().format(record))

    assert "private-value" not in payload["message"]
    assert payload["exception"]["type"] == "RuntimeError"
    assert payload["exception"]["stack"]
    assert "locals" not in payload["exception"]
