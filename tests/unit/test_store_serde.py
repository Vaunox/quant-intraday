"""Tests for the shared storage serialization / schema / range helpers (P1.3)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from quant.core.frames import BAR_COLUMNS
from quant.data.store import serde
from quant.data.store.errors import SchemaError
from tests.unit.store_fakes import IST, sample_bars

START = datetime(2026, 6, 18, 9, 15, tzinfo=IST)


def test_empty_bars_frame_has_schema_and_no_rows() -> None:
    frame = serde.empty_bars_frame()
    assert list(frame.columns) == list(BAR_COLUMNS)
    assert frame.empty


def test_ensure_bars_schema_reorders_columns() -> None:
    frame = sample_bars("RELIANCE", START, 2)[list(reversed(BAR_COLUMNS))]
    result = serde.ensure_bars_schema(frame)
    assert list(result.columns) == list(BAR_COLUMNS)


def test_ensure_bars_schema_rejects_missing_column() -> None:
    frame = sample_bars("RELIANCE", START, 1).drop(columns=["volume"])
    with pytest.raises(SchemaError, match="volume"):
        serde.ensure_bars_schema(frame)


def test_ensure_bars_schema_rejects_extra_column() -> None:
    frame = sample_bars("RELIANCE", START, 1).assign(surprise=1)
    with pytest.raises(SchemaError, match="surprise"):
        serde.ensure_bars_schema(frame)


def test_sort_bars_orders_by_timestamp_and_resets_index() -> None:
    frame = sample_bars("RELIANCE", START, 3).iloc[::-1]  # reversed rows, descending index
    result = serde.sort_bars(frame)
    assert result["timestamp"].is_monotonic_increasing
    assert list(result.index) == [0, 1, 2]


def test_restrict_to_range_is_inclusive() -> None:
    frame = sample_bars("RELIANCE", START, 5)  # 09:15 .. 09:19
    result = serde.restrict_to_range(
        frame, START + timedelta(minutes=1), START + timedelta(minutes=3)
    )
    assert len(result) == 3
    assert result["timestamp"].min() == START + timedelta(minutes=1)
    assert result["timestamp"].max() == START + timedelta(minutes=3)


def test_restrict_to_range_empty_input() -> None:
    result = serde.restrict_to_range(serde.empty_bars_frame(), START, START + timedelta(hours=1))
    assert result.empty
    assert list(result.columns) == list(BAR_COLUMNS)


def test_parquet_bytes_roundtrip_is_exact() -> None:
    frame = sample_bars("RELIANCE", START, 4)
    restored = serde.from_parquet_bytes(serde.to_parquet_bytes(frame))
    pd.testing.assert_frame_equal(frame, restored)


def test_frames_equal_is_order_insensitive() -> None:
    frame = sample_bars("RELIANCE", START, 3)
    assert serde.frames_equal(frame, frame.iloc[::-1])


def test_frames_equal_detects_difference() -> None:
    a = sample_bars("RELIANCE", START, 3)
    b = sample_bars("RELIANCE", START, 3, price=200.0)
    assert not serde.frames_equal(a, b)


def test_concat_bars_all_empty_returns_empty_schema() -> None:
    result = serde.concat_bars([serde.empty_bars_frame(), serde.empty_bars_frame()])
    assert result.empty
    assert list(result.columns) == list(BAR_COLUMNS)


def test_concat_bars_merges_and_sorts() -> None:
    first = sample_bars("RELIANCE", START, 2)
    second = sample_bars("RELIANCE", START + timedelta(minutes=2), 2)
    result = serde.concat_bars([second, first])  # out of order on purpose
    assert len(result) == 4
    assert result["timestamp"].is_monotonic_increasing
