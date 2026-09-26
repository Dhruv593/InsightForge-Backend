import json
import logging
import os
import re
import traceback
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import Settings


STANDARD_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__)
LOG_CONTEXT_FIELDS = ("request_id", "analysis_run_id", "user_id", "conversation_id", "dataset_id")
_log_context: ContextVar[dict[str, str]] = ContextVar("tatparya_log_context", default={})


@dataclass(frozen=True, slots=True)
class LoggingSetup:
    log_dir: Path
    application_log: Path | None
    error_log: Path | None


def bind_log_context(**values: Any) -> Token:
    """Attach safe correlation identifiers to every log in the current async context."""
    current = dict(_log_context.get())
    current.update({key: str(value) for key, value in values.items() if key in LOG_CONTEXT_FIELDS and value is not None})
    return _log_context.set(current)


def update_log_context(**values: Any) -> None:
    """Add identifiers for the remainder of the current request or background task."""
    current = dict(_log_context.get())
    current.update({key: str(value) for key, value in values.items() if key in LOG_CONTEXT_FIELDS and value is not None})
    _log_context.set(current)


def reset_log_context(token: Token) -> None:
    _log_context.reset(token)


class LogContextFilter(logging.Filter):
    def __init__(self, *, app_name: str, environment: str) -> None:
        super().__init__()
        self.app_name = app_name
        self.environment = environment

    def filter(self, record: logging.LogRecord) -> bool:
        context = _log_context.get()
        record.service = self.app_name
        record.environment = self.environment
        record.event = getattr(record, "event", "application.log")
        for field in LOG_CONTEXT_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, context.get(field))
        return True


def _redact(value: str) -> str:
    value = re.sub(r"https?://[^\s\"']+", "[URL redacted]", value)
    value = re.sub(r"Bearer\s+[^\s\"']+", "Bearer [redacted]", value, flags=re.I)
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;\"']+",
        r"\1\2[redacted]",
        value,
    )


class SafeFormatter(logging.Formatter):
    def formatException(self, exc_info):
        # Preserve safe frame locations while withholding messages that may contain rows or credentials.
        frames = traceback.extract_tb(exc_info[2], limit=20)
        stack = "\n".join(
            f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
            for frame in frames
        )
        return f"{stack}\n{exc_info[0].__name__}: exception details withheld" if stack else f"{exc_info[0].__name__}: exception details withheld"

    def format(self, record):
        return _redact(super().format(record))


class JsonLogFormatter(SafeFormatter):
    """Write searchable JSON Lines without serializing request or response bodies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "application.log"),
            "service": getattr(record, "service", None),
            "environment": getattr(record, "environment", None),
            "message": _redact(record.getMessage()),
        }
        for field in LOG_CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_FIELDS and key not in {*LOG_CONTEXT_FIELDS, "event", "service", "environment"} and not key.startswith("_"):
                payload[key] = self._json_value(value)
        if record.exc_info:
            frames = traceback.extract_tb(record.exc_info[2], limit=20)
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "stack": [
                    {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in frames
                ],
            }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, str):
            return _redact(value)
        if isinstance(value, list):
            return [JsonLogFormatter._json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: "[redacted]" if re.search(r"(?i)(api[_-]?key|token|secret|password)", str(key))
                else JsonLogFormatter._json_value(item)
                for key, item in value.items()
            }
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return _redact(str(value))


def setup_logging(settings: Settings) -> LoggingSetup:
    """Configure concise console logs and detailed rotating application logs."""

    log_dir = Path(settings.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for handler in root.handlers[:]:
        if getattr(handler, "_insightforge_handler", False):
            root.removeHandler(handler)
            handler.close()

    context_filter = LogContextFilter(app_name=settings.app_name, environment=settings.app_env)

    console = logging.StreamHandler()
    console._insightforge_handler = True  # type: ignore[attr-defined]
    console.setLevel(settings.console_log_level)
    console.addFilter(context_filter)
    if settings.app_env.lower() in {"production", "prod"}:
        console.setFormatter(JsonLogFormatter())
    else:
        console.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s event=%(event)s request_id=%(request_id)s analysis_run_id=%(analysis_run_id)s: %(message)s", "%H:%M:%S"))

    application_file = _rotating_handler(log_dir / "insightforge.jsonl", settings)
    if application_file is not None:
        application_file._insightforge_handler = True  # type: ignore[attr-defined]
        application_file.setLevel(settings.log_level)
        application_file.addFilter(context_filter)
        application_file.setFormatter(JsonLogFormatter())

    error_file = _rotating_handler(log_dir / "errors.jsonl", settings)
    if error_file is not None:
        error_file._insightforge_handler = True  # type: ignore[attr-defined]
        error_file.setLevel(logging.ERROR)
        error_file.addFilter(context_filter)
        error_file.setFormatter(JsonLogFormatter())

    root.addHandler(console)
    if application_file is not None:
        root.addHandler(application_file)
    if error_file is not None:
        root.addHandler(error_file)

    # SQL parameters can contain private dataset values and overwhelm application logs.
    logging.getLogger("sqlalchemy.engine").setLevel(settings.sql_log_level)
    logging.getLogger("sqlalchemy.pool").setLevel(settings.sql_log_level)
    # Route framework lifecycle/errors through the same handlers and schema.
    for name in ("uvicorn", "uvicorn.error", "gunicorn", "gunicorn.error"):
        framework_logger = logging.getLogger(name)
        framework_logger.handlers.clear()
        framework_logger.propagate = True
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = True
    uvicorn_access.setLevel(logging.WARNING)
    # HTTP clients include signed download query strings in INFO request logs.
    for name in ("httpx", "httpcore", "google", "groq", "cloudinary"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if application_file is None or error_file is None:
        root.warning(
            "File logging is unavailable; console logging remains active for log_dir=%s",
            log_dir,
            extra={"event": "logging.file.unavailable", "log_dir": str(log_dir)},
        )
    return LoggingSetup(
        log_dir=log_dir,
        application_log=Path(application_file.baseFilename) if application_file is not None else None,
        error_log=Path(error_file.baseFilename) if error_file is not None else None,
    )


def flush_logging() -> None:
    """Flush configured handlers during graceful shutdown without removing host handlers."""
    for handler in logging.getLogger().handlers:
        if getattr(handler, "_insightforge_handler", False):
            try:
                handler.flush()
            except (OSError, ValueError):
                pass


def _rotating_handler(path: Path, settings: Settings) -> RotatingFileHandler | None:
    """Use a process-specific file when another Windows process owns the base log."""

    try:
        return RotatingFileHandler(
            path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
    except OSError:
        fallback = path.with_name(f"{path.stem}-{os.getpid()}{path.suffix}")
        try:
            return RotatingFileHandler(
                fallback,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
        except OSError:
            return None
