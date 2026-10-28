"""Structured JSON logging with request correlation and secret redaction.

Every record is one JSON line. Configured secret values and bearer tokens are
replaced with [REDACTED] before output, so a stray f-string cannot leak them.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return _BEARER.sub("Bearer [REDACTED]", text)

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        entry.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return self.redact(json.dumps(entry, default=str))


def _secret_values(settings: Settings) -> list[str]:
    fields = (settings.nebius_api_key, settings.openrouter_api_key, settings.qloo_api_key, settings.supabase_jwt_secret,
              settings.supabase_secret_key)
    values = [field.get_secret_value() for field in fields if field is not None]
    if "@" in settings.database_url and "://" in settings.database_url:
        # The password segment of a database URL: scheme://user:password@host/...
        credentials = settings.database_url.split("://", 1)[1].rsplit("@", 1)[0]
        if ":" in credentials:
            values.append(credentials.split(":", 1)[1])
    return values


def configure_logging(settings: Settings) -> None:
    """Install one JSON handler on the root logger. Idempotent."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_nativeproof", False)]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(_secret_values(settings)))
    handler._nativeproof = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
