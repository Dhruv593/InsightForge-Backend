import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.core.config import Settings


STANDARD_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__)


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
        # SQL/provider exceptions can embed credentials, prompts and row values.
        return f"{exc_info[0].__name__}: exception details withheld"

    def format(self, record):
        return _redact(super().format(record))


class JsonLogFormatter(SafeFormatter):
    """Write searchable JSON Lines without serializing request or response bodies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in STANDARD_LOG_FIELDS and not key.startswith("_"):
                payload[key] = self._json_value(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
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


def setup_logging(settings: Settings) -> Path:
    """Configure concise console logs and detailed rotating application logs."""

    log_dir = Path(settings.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for handler in root.handlers[:]:
        if getattr(handler, "_insightforge_handler", False):
            root.removeHandler(handler)
            handler.close()

    console = logging.StreamHandler()
    console._insightforge_handler = True  # type: ignore[attr-defined]
    console.setLevel(settings.console_log_level)
    console.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    application_file = _rotating_handler(log_dir / "insightforge.jsonl", settings)
    if application_file is not None:
        application_file._insightforge_handler = True  # type: ignore[attr-defined]
        application_file.setLevel(settings.log_level)
        application_file.setFormatter(JsonLogFormatter())

    error_file = _rotating_handler(log_dir / "errors.jsonl", settings)
    if error_file is not None:
        error_file._insightforge_handler = True  # type: ignore[attr-defined]
        error_file.setLevel(logging.ERROR)
        error_file.setFormatter(JsonLogFormatter())

    root.addHandler(console)
    if application_file is not None:
        root.addHandler(application_file)
    if error_file is not None:
        root.addHandler(error_file)

    # SQL parameters can contain private dataset values and overwhelm application logs.
    logging.getLogger("sqlalchemy.engine").setLevel(settings.sql_log_level)
    logging.getLogger("sqlalchemy.pool").setLevel(settings.sql_log_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # HTTP clients include signed download query strings in INFO request logs.
    for name in ("httpx", "httpcore", "google", "groq", "cloudinary"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if application_file is None or error_file is None:
        root.warning("File logging is unavailable; check write permission and file locks for %s", log_dir)
    return log_dir


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
