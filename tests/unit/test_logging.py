"""Tests for structured logging (P0.3)."""

import contextvars
import io
import json
import logging
from collections.abc import Iterator

import pytest

from quant.core.config import Config, load_config
from quant.core.logging import (
    REDACTION_MASK,
    Redactor,
    configure_logging,
    correlation_id_context,
    get_correlation_id,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """Detach existing root handlers around each test so we never close pytest's."""
    root = logging.getLogger()
    saved = root.handlers[:]
    level = root.level
    for handler in saved:
        root.removeHandler(handler)
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in saved:
            root.addHandler(handler)
        root.setLevel(level)


def _json_config() -> Config:
    return load_config(env="paper", environ={})  # format=json, level=INFO


def _text_config() -> Config:
    return load_config(env="dev", environ={})  # format=text, level=DEBUG


def _log_once(config: Config, level_method: str, *args: object, **kwargs: object) -> str:
    buffer = io.StringIO()
    configure_logging(config, stream=buffer)
    getattr(get_logger("quant.test"), level_method)(*args, **kwargs)
    return buffer.getvalue()


def test_json_format_has_core_fields() -> None:
    record = json.loads(_log_once(_json_config(), "info", "hello"))
    assert record["level"] == "INFO"
    assert record["logger"] == "quant.test"
    assert record["message"] == "hello"
    assert record["correlation_id"] == "-"
    assert "timestamp" in record


def test_timestamp_is_ist() -> None:
    record = json.loads(_log_once(_json_config(), "info", "x"))
    assert "+05:30" in record["timestamp"]


def test_correlation_id_propagates_in_context() -> None:
    buffer = io.StringIO()
    configure_logging(_json_config(), stream=buffer)
    logger = get_logger("quant.test")
    with correlation_id_context("trace-123"):
        logger.info("inside")
    logger.info("outside")
    lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
    assert lines[0]["correlation_id"] == "trace-123"
    assert lines[1]["correlation_id"] == "-"


def test_correlation_id_default_is_none() -> None:
    assert get_correlation_id() is None


def test_redacts_sensitive_extra_field() -> None:
    out = _log_once(_json_config(), "info", "auth", extra={"api_key": "SUPERSECRET"})
    assert json.loads(out)["api_key"] == REDACTION_MASK
    assert "SUPERSECRET" not in out


def test_redacts_inline_bearer_token() -> None:
    out = _log_once(_json_config(), "info", "calling with Authorization Bearer abc123XYZ")
    assert "abc123XYZ" not in out
    assert REDACTION_MASK in out


def test_level_below_threshold_is_suppressed() -> None:
    assert _log_once(_json_config(), "debug", "noise") == ""  # paper level is INFO


def test_text_format_includes_fields_and_ist() -> None:
    out = _log_once(_text_config(), "info", "hi")
    assert "hi" in out
    assert "INFO" in out
    assert "[-]" in out  # correlation-id placeholder
    assert "+05:30" in out


def test_text_format_redacts() -> None:
    out = _log_once(_text_config(), "info", "header Bearer zzz999")
    assert "zzz999" not in out


def test_configure_logging_is_idempotent() -> None:
    buffer = io.StringIO()
    configure_logging(_json_config(), stream=buffer)
    configure_logging(_json_config(), stream=buffer)
    get_logger("quant.test").info("once")
    assert len(buffer.getvalue().splitlines()) == 1


def test_new_correlation_id_is_unique() -> None:
    first, second = new_correlation_id(), new_correlation_id()
    assert first != second
    assert len(first) == 16


def test_redactor_masks_by_key_and_nesting() -> None:
    redactor = Redactor()
    assert redactor.is_sensitive_key("API_KEY")
    assert redactor.redact_value("password", "x") == REDACTION_MASK
    assert redactor.redact_mapping({"a": 1, "secret": "s"}) == {"a": 1, "secret": REDACTION_MASK}
    nested = redactor.redact_mapping({"outer": {"token": "t", "ok": 2}})
    assert nested["outer"]["token"] == REDACTION_MASK
    assert nested["outer"]["ok"] == 2
    assert redactor.redact_value("items", ["plain", "Bearer tok123"]) == ["plain", REDACTION_MASK]


def test_set_correlation_id_binds_in_context() -> None:
    def _inner() -> str | None:
        set_correlation_id("manual-id")
        return get_correlation_id()

    assert contextvars.copy_context().run(_inner) == "manual-id"
    assert get_correlation_id() is None  # did not leak out of the copied context


def test_json_includes_exception() -> None:
    buffer = io.StringIO()
    configure_logging(_json_config(), stream=buffer)
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("quant.test").exception("failed")
    record = json.loads(buffer.getvalue())
    assert "exception" in record
    assert "ValueError" in record["exception"]
