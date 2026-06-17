"""Structured logging, configured once for the whole system (Ground Rule 8).

Features:

* **Structured output** - JSON (machine-queryable) or text, chosen by
  ``config.logging.format``, via the stdlib :mod:`logging` module.
* **IST timestamps** - every record is timestamped in ``config.logging.timezone``
  (Asia/Kolkata by default).
* **Correlation IDs** - a :class:`~contextvars.ContextVar` carries a correlation id
  so one decision can be traced ``decision -> order -> fill -> P&L`` across modules.
* **Secret redaction** - credentials are masked before they ever reach a handler,
  so keys/tokens never land in logs.

Call :func:`configure_logging` exactly once at startup; everywhere else use
``get_logger(__name__)``.
"""

import json
import logging
import re
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, TextIO
from zoneinfo import ZoneInfo

from quant.core.config import Config

# --------------------------------------------------------------------------- #
# Correlation IDs
# --------------------------------------------------------------------------- #

_correlation_id: ContextVar[str | None] = ContextVar("quant_correlation_id", default=None)

#: Placeholder used in records emitted outside any correlation context.
NO_CORRELATION_ID = "-"


def new_correlation_id() -> str:
    """Return a fresh, short correlation id."""
    return uuid.uuid4().hex[:16]


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, or ``None``."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Bind ``correlation_id`` to the current context (until reset/overwritten)."""
    _correlation_id.set(correlation_id)


@contextmanager
def correlation_id_context(correlation_id: str | None = None) -> Iterator[str]:
    """Bind a correlation id for the duration of the ``with`` block.

    Args:
        correlation_id: The id to bind; a fresh one is generated when ``None``.

    Yields:
        The bound correlation id.
    """
    cid = correlation_id or new_correlation_id()
    token = _correlation_id.set(cid)
    try:
        yield cid
    finally:
        _correlation_id.reset(token)


class CorrelationIdFilter(logging.Filter):
    """Stamp every record with the current correlation id."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach ``correlation_id`` to the record and let it through."""
        record.correlation_id = get_correlation_id() or NO_CORRELATION_ID
        return True


# --------------------------------------------------------------------------- #
# Redaction (never log secrets)
# --------------------------------------------------------------------------- #

#: Replacement text for anything that looks like a secret.
REDACTION_MASK = "***REDACTED***"

#: Field-name substrings whose values are always masked.
SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "private_key",
    "credential",
)

#: Backstop patterns for secrets that appear inline in message text.
_DEFAULT_PATTERNS: tuple[str, ...] = (r"(?i)\bbearer\s+[A-Za-z0-9._\-]+",)

# LogRecord attributes that are not user-supplied "extra" fields.
_RESERVED_RECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "correlation_id",
        "message",
        "asctime",
    }
)


class Redactor:
    """Masks secrets by sensitive key name and by inline pattern.

    Used by the log formatters and the audit log so credentials never reach
    persistent output.
    """

    def __init__(
        self,
        sensitive_keys: Sequence[str] = SENSITIVE_KEY_SUBSTRINGS,
        patterns: Sequence[str] = _DEFAULT_PATTERNS,
    ) -> None:
        """Build a redactor from sensitive key substrings and inline regexes."""
        self._keys = tuple(key.lower() for key in sensitive_keys)
        self._patterns = [re.compile(pattern) for pattern in patterns]

    def is_sensitive_key(self, key: str) -> bool:
        """Return whether ``key`` names a value that must be masked."""
        lowered = key.lower()
        return any(token in lowered for token in self._keys)

    def redact_text(self, text: str) -> str:
        """Mask inline secret patterns in a string."""
        result = text
        for pattern in self._patterns:
            result = pattern.sub(REDACTION_MASK, result)
        return result

    def redact_value(self, key: str, value: Any) -> Any:
        """Mask ``value`` based on its ``key`` and (recursively) its contents."""
        if self.is_sensitive_key(key):
            return REDACTION_MASK
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return self.redact_mapping(value)
        if isinstance(value, list | tuple):
            return [self.redact_value(key, item) for item in value]
        return value

    def redact_mapping(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Return a copy of ``data`` with all sensitive values masked."""
        return {key: self.redact_value(key, value) for key, value in data.items()}


# --------------------------------------------------------------------------- #
# Formatters
# --------------------------------------------------------------------------- #


class JsonFormatter(logging.Formatter):
    """Render a record as a single redacted JSON object with an IST timestamp."""

    def __init__(self, redactor: Redactor, tz: ZoneInfo) -> None:
        """Build the formatter with a redactor and the output timezone."""
        super().__init__()
        self._redactor = redactor
        self._tz = tz

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a compact JSON line."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, self._tz).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", NO_CORRELATION_ID),
            "message": self._redactor.redact_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS:
                payload[key] = self._redactor.redact_value(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable formatter with IST timestamps and correlation id; redacted."""

    # Timestamp is prepended in format() (as an IST ISO-8601 string) rather than
    # via %(asctime)s, so we don't override formatTime.
    _FORMAT = "%(levelname)-8s [%(correlation_id)s] %(name)s: %(message)s"

    def __init__(self, redactor: Redactor, tz: ZoneInfo) -> None:
        """Build the formatter with a redactor and the output timezone."""
        super().__init__(fmt=self._FORMAT)
        self._redactor = redactor
        self._tz = tz

    def format(self, record: logging.LogRecord) -> str:
        """Return the redacted line, prefixed with an IST ISO-8601 timestamp."""
        timestamp = datetime.fromtimestamp(record.created, self._tz).isoformat()
        return self._redactor.redact_text(f"{timestamp} {super().format(record)}")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def configure_logging(
    config: Config,
    *,
    stream: TextIO | None = None,
    redactor: Redactor | None = None,
) -> Redactor:
    """Configure the root logger once, from config. Safe to call again (idempotent).

    Args:
        config: System config; uses ``config.logging`` (level, format, timezone).
        stream: Output stream (defaults to ``sys.stderr``); injected in tests.
        redactor: Redactor to use (defaults to a new :class:`Redactor`).

    Returns:
        The :class:`Redactor` in force, so callers may register more secrets.
    """
    redactor = redactor or Redactor()
    tz = ZoneInfo(config.logging.timezone)
    if config.logging.format == "json":
        formatter: logging.Formatter = JsonFormatter(redactor, tz)
    else:
        formatter = TextFormatter(redactor, tz)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    root.setLevel(config.logging.level)
    return redactor


def get_logger(name: str) -> logging.Logger:
    """Return a logger; pass ``__name__`` from the calling module."""
    return logging.getLogger(name)
