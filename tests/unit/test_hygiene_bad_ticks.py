"""Tests for bad-tick filtering (P1.5) — corrections logged, never silently mutated."""

from datetime import date

import pytest

from quant.core.config import load_config
from quant.core.types import Bar
from quant.data.hygiene.bad_ticks import BadTickFilter, BadTickReason
from quant.data.store.errors import SchemaError
from tests.unit.hygiene_fakes import at, bar, frame, good

DAY = date(2024, 6, 3)


def _mixed_bars() -> list[Bar]:
    """A session with one bad bar of each kind interleaved with good bars."""
    return [
        good("X", at(DAY, 9, 15), 100.0),  # ok (first bar, no spike check)
        good("X", at(DAY, 9, 16), 101.0),  # ok (+1%)
        bar("X", at(DAY, 9, 17), o=50, h=50, lo=0, c=0, v=10),  # non-positive price
        good("X", at(DAY, 9, 18), 102.0),  # ok vs last valid (101)
        bar("X", at(DAY, 9, 19), o=100, h=100, lo=110, c=100, v=10),  # high < low
        bar("X", at(DAY, 9, 20), o=100, h=101, lo=99, c=100, v=-5),  # negative volume
        bar("X", at(DAY, 9, 21), o=200, h=201, lo=199, c=200, v=10),  # spike vs 102 (+96%)
        good("X", at(DAY, 9, 22), 103.0),  # ok vs last *valid* (102), not the spike
    ]


def test_removes_each_bad_kind_and_keeps_good() -> None:
    result = BadTickFilter(max_move_pct=20.0).filter("X", frame(_mixed_bars()))

    kept = result.clean["timestamp"].dt.strftime("%H:%M").tolist()
    assert kept == ["09:15", "09:16", "09:18", "09:22"]
    assert result.removed == 4
    reasons = [c.reason for c in result.corrections]
    assert reasons == [
        BadTickReason.NON_POSITIVE_PRICE,
        BadTickReason.OHLC_INCONSISTENT,
        BadTickReason.NEGATIVE_VOLUME,
        BadTickReason.PRICE_SPIKE,
    ]


def test_spike_compares_to_previous_valid_not_removed_bar() -> None:
    # The 09:22 bar (103) survives because the spike (200) was removed and the previous
    # *valid* close stays 102 — proving the spike test uses point-in-time valid history.
    result = BadTickFilter(max_move_pct=20.0).filter("X", frame(_mixed_bars()))
    assert at(DAY, 9, 22) in set(result.clean["timestamp"])


def test_corrections_carry_symbol_and_timestamp() -> None:
    result = BadTickFilter(max_move_pct=20.0).filter("X", frame(_mixed_bars()))
    spike = next(c for c in result.corrections if c.reason is BadTickReason.PRICE_SPIKE)
    assert spike.symbol == "X"
    assert spike.timestamp == at(DAY, 9, 21)
    assert "C=200" in spike.detail


def test_idempotent_refilter_removes_nothing() -> None:
    flt = BadTickFilter(max_move_pct=20.0)
    once = flt.filter("X", frame(_mixed_bars()))
    twice = flt.filter("X", once.clean)
    assert twice.removed == 0
    assert twice.clean.equals(once.clean)


def test_all_good_bars_pass_through() -> None:
    bars = frame([good("X", at(DAY, 9, 15 + i), 100.0 + i) for i in range(5)])
    result = BadTickFilter(max_move_pct=20.0).filter("X", bars)
    assert result.removed == 0
    assert len(result.clean) == 5


def test_from_config_uses_threshold() -> None:
    flt = BadTickFilter.from_config(load_config(environ={}).hygiene)
    # default.yaml threshold is 20%; a 25% jump is a spike.
    bars = frame([good("X", at(DAY, 9, 15), 100.0), good("X", at(DAY, 9, 16), 125.0)])
    assert flt.filter("X", bars).removed == 1


def test_non_positive_threshold_rejected() -> None:
    with pytest.raises(ValueError, match="max_move_pct"):
        BadTickFilter(max_move_pct=0.0)


def test_empty_frame_is_clean() -> None:
    result = BadTickFilter(max_move_pct=20.0).filter("X", frame([]))
    assert result.removed == 0
    assert result.clean.empty


def test_bad_schema_rejected() -> None:
    with pytest.raises(SchemaError):
        BadTickFilter(max_move_pct=20.0).filter("X", frame(_mixed_bars()).drop(columns=["high"]))
