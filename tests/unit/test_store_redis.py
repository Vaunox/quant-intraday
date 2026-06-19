"""Tests for RedisLiveStore — the bounded recent-bars hot tier (P1.3).

Redis is optional and not installed in CI; the store logic is verified against
:class:`FakeRedisClient`. The lazy factory's missing-dependency path is also exercised.
"""

import importlib.util
from datetime import datetime, timedelta

import pandas as pd
import pytest

from quant.core.config import load_config
from quant.core.frames import BAR_COLUMNS
from quant.core.interfaces import Repository
from quant.data.store.errors import OptionalDependencyError, SchemaError
from quant.data.store.redis_store import (
    RedisLiveStore,
    create_redis_client,
    create_redis_live_store,
)
from tests.unit.store_fakes import IST, FakeRedisClient, sample_bars

DAY1 = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
HOUR = timedelta(hours=1)
_REDIS_INSTALLED = importlib.util.find_spec("redis") is not None


def _store(*, max_bars: int = 100, ttl_seconds: int = 0) -> tuple[RedisLiveStore, FakeRedisClient]:
    client = FakeRedisClient()
    store = RedisLiveStore(client, key_prefix="quant", max_bars=max_bars, ttl_seconds=ttl_seconds)
    return store, client


def test_is_a_repository() -> None:
    store, _ = _store()
    assert isinstance(store, Repository)


def test_write_read_roundtrip() -> None:
    store, _ = _store()
    bars = sample_bars("RELIANCE", DAY1, 4)
    store.write_bars("RELIANCE", bars)
    pd.testing.assert_frame_equal(store.read_bars("RELIANCE", DAY1, DAY1 + HOUR), bars)


def test_keys_are_namespaced_by_prefix() -> None:
    store, client = _store()
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    assert "quant:bars:RELIANCE" in client.kv
    assert client.sets["quant:symbols"] == {"RELIANCE"}


def test_rolling_window_trims_to_max_bars() -> None:
    store, _ = _store(max_bars=4)
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1 + timedelta(minutes=3), 3))
    result = store.read_bars("RELIANCE", DAY1, DAY1 + HOUR)
    assert len(result) == 4  # 6 written, only the newest 4 retained
    assert result["timestamp"].min() == DAY1 + timedelta(minutes=2)


def test_overlapping_write_dedupes_with_incoming_winning() -> None:
    store, _ = _store()
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3, price=100.0))  # t0..t2
    store.write_bars(
        "RELIANCE", sample_bars("RELIANCE", DAY1 + timedelta(minutes=1), 3, price=200.0)
    )  # t1..t3
    result = store.read_bars("RELIANCE", DAY1, DAY1 + HOUR)
    assert len(result) == 4  # t0, t1, t2, t3 (no duplicate timestamps)
    t1_close = result.loc[result["timestamp"] == DAY1 + timedelta(minutes=1), "close"].iloc[0]
    assert t1_close == 200.5  # the later (incoming) value won


def test_idempotent_rewrite_keeps_window_stable() -> None:
    store, _ = _store(max_bars=10)
    bars = sample_bars("RELIANCE", DAY1, 3)
    store.write_bars("RELIANCE", bars)
    store.write_bars("RELIANCE", bars)
    assert len(store.read_bars("RELIANCE", DAY1, DAY1 + HOUR)) == 3


def test_ttl_passed_when_configured() -> None:
    store, client = _store(ttl_seconds=30)
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    assert client.set_calls == [("quant:bars:RELIANCE", 30)]


def test_no_ttl_when_zero() -> None:
    store, client = _store(ttl_seconds=0)
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    assert client.set_calls == [("quant:bars:RELIANCE", None)]


def test_range_filter() -> None:
    store, _ = _store()
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 10))
    result = store.read_bars("RELIANCE", DAY1 + timedelta(minutes=1), DAY1 + timedelta(minutes=3))
    assert len(result) == 3


def test_list_symbols_sorted() -> None:
    store, _ = _store()
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    store.write_bars("INFY", sample_bars("INFY", DAY1, 1))
    assert list(store.list_symbols()) == ["INFY", "RELIANCE"]


def test_read_unknown_symbol_returns_empty() -> None:
    store, _ = _store()
    empty = store.read_bars("INFY", DAY1, DAY1 + HOUR)
    assert empty.empty
    assert list(empty.columns) == list(BAR_COLUMNS)


def test_empty_write_is_noop() -> None:
    store, client = _store()
    store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 0))
    assert client.set_calls == []
    assert list(store.list_symbols()) == []


def test_write_rejects_bad_schema() -> None:
    store, _ = _store()
    with pytest.raises(SchemaError):
        store.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1).drop(columns=["high"]))


def test_non_positive_max_bars_rejected() -> None:
    with pytest.raises(ValueError, match="max_bars"):
        RedisLiveStore(FakeRedisClient(), key_prefix="quant", max_bars=0)


@pytest.mark.skipif(_REDIS_INSTALLED, reason="redis installed; missing-dep path not hit")
def test_create_redis_client_without_redis_raises() -> None:
    with pytest.raises(OptionalDependencyError, match="redis is not installed"):
        create_redis_client("redis://localhost:6379/0")


@pytest.mark.skipif(_REDIS_INSTALLED, reason="redis installed; missing-dep path not hit")
def test_create_redis_live_store_without_redis_raises() -> None:
    with pytest.raises(OptionalDependencyError):
        create_redis_live_store(load_config(environ={}).storage)
