"""Step 2 ETF bid-ask spread + depth analysis (multi-ETF rotation track).

Pure aggregation over live quote snapshots. The Kite ``quote()`` polling that produces the
snapshots lives in the thin ``scripts/etf_spread_sampler.py`` shim (Ground Rule 3).

The bid-ask spread is the dominant *trading* cost at the Rs 1 lakh rebalance scale
(SPEC_MultiETF_Rotation.md Section 6 — STT is resolved as negligible, so spread + the flat
DP charge dominate). This module measures spread per leg: the median, the tail (a thin leg
that is usually fine but blows out intermittently still eats the edge on those rebalances),
and the top-of-book depth.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    """One top-of-book snapshot for a symbol.

    Attributes:
        symbol: Ticker.
        ts: Snapshot time.
        bid: Best bid price (Rs).
        ask: Best ask price (Rs).
        bid_qty: Quantity available at the best bid (units).
        ask_qty: Quantity available at the best ask (units).
    """

    symbol: str
    ts: datetime
    bid: float
    ask: float
    bid_qty: int
    ask_qty: int

    @property
    def mid(self) -> float:
        """Mid price: the average of best bid and best ask (Rs)."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        """Round-trip spread cost in basis points: ``(ask - bid) / mid * 1e4``.

        Crossing the spread once each way (buy at the ask, later sell at the bid) costs
        approximately the full quoted spread, so this is the per-leg round-trip estimate.
        """
        return (self.ask - self.bid) / self.mid * 1e4

    @property
    def is_valid(self) -> bool:
        """Whether the snapshot is a usable two-sided quote (positive, not crossed)."""
        return self.bid > 0 and self.ask > 0 and self.ask >= self.bid


@dataclass(frozen=True, slots=True)
class SpreadStat:
    """Per-symbol spread/depth summary over a sampling window.

    Attributes:
        symbol: Ticker.
        samples: Number of valid snapshots aggregated.
        median_spread_bps: Median round-trip spread (bps).
        p90_spread_bps: 90th-percentile spread (the tail).
        max_spread_bps: Worst observed spread (bps).
        median_top_depth_units: Median of ``min(bid_qty, ask_qty)`` — tradeable units at top.
    """

    symbol: str
    samples: int
    median_spread_bps: float
    p90_spread_bps: float
    max_spread_bps: float
    median_top_depth_units: float


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted, non-empty sequence."""
    if not sorted_vals:
        raise ValueError("quantile of empty sequence")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    low = int(pos)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = pos - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def summarize(snapshots: Sequence[QuoteSnapshot]) -> list[SpreadStat]:
    """Aggregate snapshots into per-symbol spread stats, tightest median spread first.

    Invalid snapshots (zero or crossed quotes — transient feed glitches) are dropped.

    Args:
        snapshots: Quote snapshots across one or more sessions, any symbol order.

    Returns:
        Per-symbol :class:`SpreadStat`, sorted by median spread ascending.

    Raises:
        ValueError: If no valid snapshots exist for any symbol.
    """
    by_symbol: dict[str, list[QuoteSnapshot]] = {}
    for snap in snapshots:
        if snap.is_valid:
            by_symbol.setdefault(snap.symbol, []).append(snap)
    if not by_symbol:
        raise ValueError("no valid snapshots to summarize")
    stats = [
        SpreadStat(
            symbol=symbol,
            samples=len(snaps),
            median_spread_bps=statistics.median(s.spread_bps for s in snaps),
            p90_spread_bps=_quantile(sorted(s.spread_bps for s in snaps), 0.90),
            max_spread_bps=max(s.spread_bps for s in snaps),
            median_top_depth_units=statistics.median(
                float(min(s.bid_qty, s.ask_qty)) for s in snaps
            ),
        )
        for symbol, snaps in by_symbol.items()
    ]
    stats.sort(key=lambda stat: stat.median_spread_bps)
    return stats
