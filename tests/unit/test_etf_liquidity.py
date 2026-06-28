"""Unit tests for the Step 1 ETF universe liquidity gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quant.research.etf.liquidity import (
    DailyBar,
    LiquidityGate,
    LiquidityStat,
    assess_symbol,
    market_wide_dead_dates,
    run_gate,
)


def _series(start: date, closes_volumes: list[tuple[float, float]]) -> list[DailyBar]:
    """Build a consecutive-day bar series from (close, volume) pairs."""
    return [
        DailyBar(day=start + timedelta(days=i), close=c, volume=v)
        for i, (c, v) in enumerate(closes_volumes)
    ]


def test_traded_value_is_close_times_volume() -> None:
    assert DailyBar(date(2026, 1, 1), close=100.0, volume=5.0).traded_value == 500.0


def test_market_wide_dead_date_flagged_but_single_symbol_zero_is_not() -> None:
    start = date(2026, 1, 1)
    # Day index 1 is zero-volume for BOTH symbols (a holiday); day 2 only for one symbol.
    panel = {
        "A": _series(start, [(10.0, 100.0), (10.0, 0.0), (10.0, 0.0), (10.0, 100.0)]),
        "B": _series(start, [(20.0, 100.0), (20.0, 0.0), (20.0, 50.0), (20.0, 100.0)]),
    }
    dead = market_wide_dead_dates(panel, max_alive=0)
    assert start + timedelta(days=1) in dead  # both dead -> artifact
    assert start + timedelta(days=2) not in dead  # only A dead -> real, kept


def test_holiday_present_in_only_a_majority_is_still_flagged() -> None:
    # Regression: a real market holiday is carried inconsistently by the feed — present in a
    # majority of symbols but not all. It must still be flagged (the bug was requiring it in
    # ~every symbol). A sparse date held by a single symbol must NOT be flagged.
    holiday = date(2026, 1, 15)
    sparse = date(2020, 1, 1)
    panel = {
        "A": [DailyBar(sparse, 10.0, 5.0), DailyBar(holiday, 10.0, 0.0)],
        "B": [DailyBar(holiday, 20.0, 0.0)],
        "C": [DailyBar(holiday, 30.0, 0.0)],
        "D": [DailyBar(holiday, 40.0, 100.0)],  # one symbol's feed shows a tiny holiday print
    }
    dead = market_wide_dead_dates(panel, max_alive=1, min_present_fraction=0.5)
    assert holiday in dead  # present in 4/4, only 1 traded -> non-session
    assert sparse not in dead  # present in 1/4 -> not broad, kept


def test_assess_symbol_excludes_dead_dates_and_computes_stats() -> None:
    start = date(2026, 1, 1)
    bars = _series(start, [(10.0, 100.0), (10.0, 0.0), (10.0, 300.0)])
    dead = frozenset({start + timedelta(days=1)})
    stat = assess_symbol("A", bars, dead_dates=dead, window=252)
    assert stat.sessions == 2  # the dead day dropped
    assert stat.continuity_pct == 100.0  # both remaining sessions traded
    # remaining traded values: 1000 and 3000 -> median 2000
    assert stat.median_traded_value == 2000.0
    assert stat.window_start == start


def test_assess_symbol_honours_window_length() -> None:
    start = date(2026, 1, 1)
    bars = _series(start, [(1.0, 10.0)] * 10)
    stat = assess_symbol("A", bars, dead_dates=frozenset(), window=3)
    assert stat.sessions == 3
    assert stat.window_start == start + timedelta(days=7)


def test_assess_symbol_raises_when_all_sessions_dead() -> None:
    start = date(2026, 1, 1)
    bars = _series(start, [(1.0, 0.0), (1.0, 0.0)])
    dead = frozenset({start, start + timedelta(days=1)})
    with pytest.raises(ValueError, match="no live sessions"):
        assess_symbol("A", bars, dead_dates=dead, window=252)


def _stat(median: float, continuity: float) -> LiquidityStat:
    """Build a LiquidityStat with the non-varying fields fixed."""
    return LiquidityStat(
        symbol="A",
        window_start=date(2026, 1, 1),
        sessions=252,
        median_traded_value=median,
        continuity_pct=continuity,
    )


def test_liquidity_stat_passes_requires_both_thresholds() -> None:
    gate = LiquidityGate(min_median_traded_value=5e7, min_continuity_pct=99.0)
    assert _stat(median=6e7, continuity=100.0).passes(gate)
    assert not _stat(median=4e7, continuity=100.0).passes(gate)
    assert not _stat(median=6e7, continuity=98.0).passes(gate)


def test_run_gate_sorts_by_liquidity_and_applies_dead_dates() -> None:
    start = date(2026, 1, 1)
    panel = {
        "THIN": _series(start, [(10.0, 10.0), (10.0, 0.0), (10.0, 10.0)]),
        "THICK": _series(start, [(10.0, 100.0), (10.0, 0.0), (10.0, 100.0)]),
    }
    gate = LiquidityGate(min_median_traded_value=500.0, min_continuity_pct=99.0)
    stats = run_gate(panel, gate, max_alive=0)
    assert [s.symbol for s in stats] == ["THICK", "THIN"]  # sorted desc
    # the shared zero-volume middle day is an artifact -> both report 100% continuity
    assert all(s.continuity_pct == 100.0 for s in stats)
    assert stats[0].passes(gate)  # THICK: median 1000 >= 500
    assert not stats[1].passes(gate)  # THIN: median 100 < 500
