"""
Structured JSON logging with no logging platform behind it: one JSON object per line on stdout.

Every entry carries the request id of the request that caused it (including the background analysis it started),
and call sites add fields such as upload_id, module, duration_ms, status and error_code through log_event().
Sensitive material is kept out in two layers: call sites never pass transaction text, and the formatter drops
sensitive field names and redacts token / credential patterns as a safety net.
"""
import json
import logging
import re
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from backend.core.config import log_exception_messages, settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Field names that must never be written, whatever the caller passes.
SENSITIVE_FIELDS = frozenset(
    {
        "password", "passwd", "token", "access_token", "authorization", "cookie", "secret", "jwt_secret",
        "database_url", "description", "descriptions", "text", "rows", "row", "body", "email",
    }
)
_REDACTIONS = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[redacted-token]"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "bearer [redacted]"),
    (re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+:[^@\s]+@"), r"\1[redacted]@"),
]
_HANDLER_TAG = "_finsight_json_handler"
_MAX_VALUE_LENGTH = 300


def _install_request_id_capture() -> None:
    """Stamp every log record with the current request id at the moment it is created (not when it is formatted)."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "_finsight_request_id", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    factory._finsight_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


_install_request_id_capture()


def redact_text(value: str) -> str:
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)[:_MAX_VALUE_LENGTH]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value))[:_MAX_VALUE_LENGTH]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": redact_text(record.getMessage())[:_MAX_VALUE_LENGTH],
            "logger": record.name,
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for key, value in getattr(record, "fields", {}).items():
            if key.lower() not in SENSITIVE_FIELDS and key not in entry:
                entry[key] = _clean_value(value)
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc, tb = record.exc_info
            entry["exc_type"] = exc_type.__name__
            # Frames (file, line, function) always. The exception *message* only if explicitly enabled for local
            # debugging (LOG_EXCEPTION_MESSAGES=true): it can echo user data, so it is off by default everywhere.
            frames = traceback.format_tb(tb)
            entry["stack"] = redact_text("".join(frames))[-2000:]
            if log_exception_messages():
                entry["error"] = redact_text(str(exc))[:_MAX_VALUE_LENGTH]
        return json.dumps(entry, default=str)


def log_event(logger: logging.Logger, level: int, event: str, exc_info: Any = None, **fields: Any) -> None:
    """Log a named event with structured fields. Never pass transaction text, passwords or tokens."""
    logger.log(level, event, extra={"fields": fields}, exc_info=exc_info)


def configure_logging() -> None:
    """Idempotently send JSON logs to stdout. Safe to call more than once and from tests."""
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    # A JSON handler may already be installed by the server's own log config (backend/logging_config.json).
    if not any(getattr(h, _HANDLER_TAG, False) or isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)
    # uvicorn installs its own plain-text handlers; send its error log through ours and silence its access log
    # (the request middleware logs each request as a structured event instead).
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers = []
        uv.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
