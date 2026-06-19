"""Tests for KiteAdapter — the market-data path and session/contract guarantees (P1.1)."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from quant.core.frames import BAR_COLUMNS
from quant.core.interfaces import BrokerAdapter
from quant.core.types import OrderRequest, OrderType, Side
from quant.data.brokers.auth import InMemoryTokenStore
from quant.data.brokers.errors import (
    InstrumentNotFoundError,
    SessionNotSeededError,
    UnsupportedIntervalError,
)
from quant.data.brokers.instruments import InstrumentRegistry
from quant.data.brokers.kite import KiteAdapter
from quant.data.brokers.rate_limit import TokenBucketRateLimiter
from tests.unit.brokers_fakes import (
    RELIANCE_TOKEN,
    CountingRateLimiter,
    FakeClock,
    FakeKiteClient,
    sample_instruments,
)

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
END = datetime(2026, 6, 18, 15, 30, tzinfo=IST)


def _make_adapter(
    *,
    client: FakeKiteClient | None = None,
    seeded: bool = True,
    rate_limiter: Any | None = None,
) -> tuple[KiteAdapter, FakeKiteClient]:
    client = client or FakeKiteClient()
    store = InMemoryTokenStore()
    if seeded:
        store.set_access_token("access-token")
    clock = FakeClock()
    limiter = rate_limiter or TokenBucketRateLimiter(
        3, monotonic=clock.monotonic, sleep=clock.sleep
    )
    registry = InstrumentRegistry(sample_instruments())
    adapter = KiteAdapter(client, store, registry, limiter, exchange="NSE")
    return adapter, client


def test_is_a_broker_adapter() -> None:
    adapter, _ = _make_adapter()
    assert isinstance(adapter, BrokerAdapter)


def test_fetch_historical_returns_canonical_frame() -> None:
    adapter, client = _make_adapter()
    frame = adapter.fetch_historical("RELIANCE", START, END, "minute")

    assert list(frame.columns) == list(BAR_COLUMNS)
    assert len(frame) == 3
    assert (frame["symbol"] == "RELIANCE").all()
    assert frame["close"].tolist() == [101.0, 101.8, 102.2]
    assert frame["volume"].tolist() == [12000, 9000, 15000]
    # tz-aware IST timestamps are preserved from the broker response.
    assert frame["timestamp"].iloc[0] == START


def test_fetch_historical_calls_sdk_with_resolved_token_and_range() -> None:
    adapter, client = _make_adapter()
    adapter.fetch_historical("RELIANCE", START, END, "minute")

    assert len(client.historical_calls) == 1
    call = client.historical_calls[0]
    assert call["instrument_token"] == RELIANCE_TOKEN
    assert call["interval"] == "minute"
    assert call["from_date"] == START
    assert call["to_date"] == END


def test_fetch_historical_normalizes_interval_aliases() -> None:
    adapter, client = _make_adapter()
    adapter.fetch_historical("RELIANCE", START, END, "15minute")
    adapter.fetch_historical("RELIANCE", START, END, "1minute")  # alias of "minute"
    assert [c["interval"] for c in client.historical_calls] == ["15minute", "minute"]


def test_fetch_historical_applies_current_token_to_client() -> None:
    adapter, client = _make_adapter()
    adapter.fetch_historical("RELIANCE", START, END, "minute")
    assert client.access_token == "access-token"


def test_fetch_historical_empty_result_has_schema() -> None:
    adapter, _ = _make_adapter(client=FakeKiteClient(candles=[]))
    frame = adapter.fetch_historical("RELIANCE", START, END, "minute")
    assert list(frame.columns) == list(BAR_COLUMNS)
    assert frame.empty


def test_fetch_historical_throttles_once_per_call() -> None:
    limiter = CountingRateLimiter()
    adapter, _ = _make_adapter(rate_limiter=limiter)
    adapter.fetch_historical("RELIANCE", START, END, "minute")
    adapter.fetch_historical("INFY", START, END, "minute")
    assert limiter.calls == 2


def test_unseeded_session_raises_and_makes_no_call() -> None:
    limiter = CountingRateLimiter()
    adapter, client = _make_adapter(seeded=False, rate_limiter=limiter)
    with pytest.raises(SessionNotSeededError):
        adapter.fetch_historical("RELIANCE", START, END, "minute")
    # Fail before touching the data endpoint or spending a rate-limit token.
    assert client.historical_calls == []
    assert limiter.calls == 0


def test_unknown_symbol_raises_before_call() -> None:
    limiter = CountingRateLimiter()
    adapter, client = _make_adapter(rate_limiter=limiter)
    with pytest.raises(InstrumentNotFoundError):
        adapter.fetch_historical("UNKNOWN", START, END, "minute")
    assert client.historical_calls == []
    assert limiter.calls == 0  # don't waste throttle budget on a call that won't happen


def test_bad_interval_raises() -> None:
    adapter, _ = _make_adapter()
    with pytest.raises(UnsupportedIntervalError):
        adapter.fetch_historical("RELIANCE", START, END, "2minute")


def test_bad_candle_timestamp_type_fails_loud() -> None:
    bad = [{"date": "2026-06-18", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}]
    adapter, _ = _make_adapter(client=FakeKiteClient(candles=bad))
    with pytest.raises(TypeError, match="datetime"):
        adapter.fetch_historical("RELIANCE", START, END, "minute")


_ORDER = OrderRequest("RELIANCE", Side.BUY, 1, OrderType.MARKET)

_DEFERRED_CALLS: list[Callable[[KiteAdapter], Any]] = [
    lambda a: a.place_order(_ORDER),
    lambda a: a.modify_order("id", _ORDER),
    lambda a: a.cancel_order("id"),
    lambda a: a.get_order("id"),
    lambda a: a.get_orders(),
    lambda a: a.get_positions(),
    lambda a: a.margins(),
]


@pytest.mark.parametrize("call", _DEFERRED_CALLS)
def test_trading_and_account_methods_are_deferred(call: Callable[[KiteAdapter], Any]) -> None:
    adapter, _ = _make_adapter()
    with pytest.raises(NotImplementedError):
        call(adapter)
