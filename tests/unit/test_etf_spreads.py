"""Unit tests for the Step 2 ETF spread/depth analysis."""

from __future__ import annotations

from datetime import datetime

import pytest

from quant.research.etf.spreads import QuoteSnapshot, summarize


def _snap(
    symbol: str, bid: float, ask: float, bid_qty: int = 100, ask_qty: int = 100
) -> QuoteSnapshot:
    """Build a snapshot with a fixed timestamp."""
    return QuoteSnapshot(
        symbol=symbol,
        ts=datetime(2026, 6, 29, 10, 0, 0),
        bid=bid,
        ask=ask,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
    )


def test_spread_bps_and_mid() -> None:
    snap = _snap("NIFTYBEES", bid=99.0, ask=101.0)
    assert snap.mid == 100.0
    assert snap.spread_bps == pytest.approx(200.0)  # 2 / 100 * 1e4


def test_validity_filters_zero_and_crossed_quotes() -> None:
    assert _snap("A", 100.0, 100.2).is_valid
    assert not _snap("A", 0.0, 100.2).is_valid  # no bid
    assert not _snap("A", 100.2, 100.0).is_valid  # crossed


def test_summarize_drops_invalid_and_sorts_by_median_spread() -> None:
    snaps = [
        _snap("WIDE", 100.0, 101.0),  # 100 bps
        _snap("WIDE", 100.0, 101.0),
        _snap("TIGHT", 100.0, 100.1),  # 10 bps
        _snap("TIGHT", 100.0, 100.1),
        _snap("TIGHT", 100.2, 100.0),  # crossed -> dropped
    ]
    stats = summarize(snaps)
    assert [s.symbol for s in stats] == ["TIGHT", "WIDE"]  # tightest first
    tight = stats[0]
    assert tight.samples == 2  # crossed snapshot dropped
    assert tight.median_spread_bps == pytest.approx(10.0, rel=1e-3)


def test_summarize_reports_tail_and_top_depth() -> None:
    # nine 10bps snapshots and one 50bps blowout -> p90 picks up the tail
    snaps = [_snap("X", 100.0, 100.1, bid_qty=500, ask_qty=300) for _ in range(9)]
    snaps.append(_snap("X", 100.0, 100.5, bid_qty=500, ask_qty=300))
    (stat,) = summarize(snaps)
    assert stat.median_spread_bps == pytest.approx(0.1 / 100.05 * 1e4, rel=1e-3)
    assert stat.p90_spread_bps > stat.median_spread_bps  # tail captured
    assert stat.max_spread_bps == pytest.approx(0.5 / 100.25 * 1e4, rel=1e-3)
    assert stat.median_top_depth_units == 300.0  # min(bid_qty, ask_qty)


def test_summarize_raises_when_all_invalid() -> None:
    with pytest.raises(ValueError, match="no valid snapshots"):
        summarize([_snap("A", 0.0, 0.0)])
