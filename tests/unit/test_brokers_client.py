"""Tests for the Kite SDK seam: interval normalization + the client factory (P1.1)."""

from typing import Any

import pytest

from quant.data.brokers.client import (
    KITE_INTERVALS,
    KiteClient,
    create_kite_client,
    normalize_interval,
)
from quant.data.brokers.errors import UnsupportedIntervalError
from tests.unit.brokers_fakes import FakeKiteClient


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("minute", "minute"),
        ("1minute", "minute"),
        ("MINUTE", "minute"),
        (" 5minute ", "5minute"),
        ("15minute", "15minute"),
        ("60minute", "60minute"),
        ("hour", "60minute"),
        ("day", "day"),
        ("Day", "day"),
    ],
)
def test_normalize_interval(given: str, expected: str) -> None:
    assert normalize_interval(given) == expected


def test_normalize_interval_rejects_unknown() -> None:
    with pytest.raises(UnsupportedIntervalError, match="7minute"):
        normalize_interval("7minute")


def test_canonical_intervals_are_fixed_points() -> None:
    # Every canonical interval normalizes to itself (no alias points outside the set).
    assert {"minute", "day", "15minute"} <= KITE_INTERVALS
    for interval in KITE_INTERVALS:
        assert normalize_interval(interval) == interval


def test_fake_client_satisfies_protocol() -> None:
    # Static (mypy) + runtime: the fake stands in for the real SDK client.
    client: KiteClient = FakeKiteClient()
    assert client.login_url().startswith("https://")


def test_create_kite_client_passes_all_args(monkeypatch: pytest.MonkeyPatch) -> None:
    kite = pytest.importorskip("kiteconnect")
    captured: dict[str, Any] = {}

    class FakeKiteConnect:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(kite, "KiteConnect", FakeKiteConnect)
    client = create_kite_client("api123", root="https://api.kite.trade", timeout=10)
    assert isinstance(client, FakeKiteConnect)
    assert captured == {"api_key": "api123", "root": "https://api.kite.trade", "timeout": 10}


def test_create_kite_client_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    kite = pytest.importorskip("kiteconnect")
    captured: dict[str, Any] = {}

    class FakeKiteConnect:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(kite, "KiteConnect", FakeKiteConnect)
    create_kite_client("api123")
    assert captured == {"api_key": "api123"}  # no root/timeout unless provided
