"""Step 1 universe liquidity gate for the multi-ETF rotation track.

Pure, testable logic for SPEC_MultiETF_Rotation.md Section 7, Step 1: given daily bars
per candidate ETF, decide which clear a turnover floor at the ``Rs 1 lakh`` rebalance
scale. Network I/O (the Yahoo daily fetch) lives in the thin
``scripts/etf_liquidity_gate.py`` shim (Ground Rule 3); everything here is a pure
function over in-memory bars, so it unit-tests without a live feed.

A subtlety this module exists to handle correctly: a market-wide holiday or feed gap shows
up as a zero-volume row carried with a forward-filled close across (nearly) the *whole*
panel. That is a non-session, not an ETF failing to trade, and must be excluded before
continuity is measured — otherwise a genuinely liquid ETF looks like it skipped sessions.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One daily bar reduced to the fields the gate needs.

    Attributes:
        day: Session date.
        close: Close price (Rs). Bars with a missing close are dropped before construction.
        volume: Traded quantity (units). Zero marks a non-trading or data-gap day.
    """

    day: date
    close: float
    volume: float

    @property
    def traded_value(self) -> float:
        """Daily traded value in Rs (the turnover proxy): ``close * volume``."""
        return self.close * self.volume


@dataclass(frozen=True, slots=True)
class LiquidityGate:
    """Pre-registered Step 1 gate thresholds.

    The committed values live in ``docs/etf_rotation/step1_liquidity_gate.md`` and count
    toward honest N; changing them is a registered trial, not a tweak.

    Attributes:
        min_median_traded_value: Floor on the trailing-window median daily traded value (Rs).
        min_continuity_pct: Floor on the share of live sessions with positive volume.
        window: Number of trailing genuine sessions to measure over.
    """

    min_median_traded_value: float
    min_continuity_pct: float
    window: int = 252


@dataclass(frozen=True, slots=True)
class LiquidityStat:
    """Measured liquidity for one symbol over the trailing window.

    Attributes:
        symbol: Ticker.
        window_start: Date of the first session in the measured window.
        sessions: Number of live sessions measured (<= ``gate.window``).
        median_traded_value: Median daily traded value over the window (Rs).
        continuity_pct: Share of measured sessions with positive volume.
    """

    symbol: str
    window_start: date
    sessions: int
    median_traded_value: float
    continuity_pct: float

    def passes(self, gate: LiquidityGate) -> bool:
        """Return whether this symbol clears ``gate``."""
        return (
            self.median_traded_value >= gate.min_median_traded_value
            and self.continuity_pct >= gate.min_continuity_pct
        )


def market_wide_dead_dates(
    panel: Mapping[str, Sequence[DailyBar]],
    *,
    max_alive: int = 1,
    min_present_fraction: float = 0.5,
) -> frozenset[date]:
    """Find non-session / data-artifact dates rather than real no-trade days.

    A date is flagged when two independent conditions both hold: (1) at most ``max_alive``
    symbols actually traded (volume > 0) on it, and (2) the date is *broad* — present in at
    least ``min_present_fraction`` of the panel. A genuine market holiday shows zero volume
    across unrelated ETFs simultaneously; real illiquidity in one ETF does not coincide
    across the panel, and a real trading day has many symbols trading (so it is never
    flagged even if a handful carry a Yahoo volume gap).

    The two conditions are deliberately decoupled: holiday rows are carried *inconsistently*
    by the data feed (some symbols omit the date or null its close), so a date can be a true
    non-session while present in only, say, 10 of 12 symbols. Tying "broad" to ``max_alive``
    would let such dates slip through.

    Args:
        panel: Mapping of symbol to its daily bars.
        max_alive: Maximum symbols allowed to be trading for the date to still count as dead.
        min_present_fraction: Minimum share of the panel that must carry the date for it to
            be considered broad (guards against flagging a sparse early date held by one
            symbol).

    Returns:
        The set of artifact / non-session dates.
    """
    present_by_date: dict[date, int] = {}
    alive_by_date: dict[date, int] = {}
    for bars in panel.values():
        for bar in bars:
            present_by_date[bar.day] = present_by_date.get(bar.day, 0) + 1
            if bar.volume > 0:
                alive_by_date[bar.day] = alive_by_date.get(bar.day, 0) + 1
    min_present = math.ceil(len(panel) * min_present_fraction)
    return frozenset(
        day
        for day, present in present_by_date.items()
        if present >= min_present and alive_by_date.get(day, 0) <= max_alive
    )


def assess_symbol(
    symbol: str,
    bars: Sequence[DailyBar],
    *,
    dead_dates: frozenset[date],
    window: int,
) -> LiquidityStat:
    """Measure trailing-window liquidity for one symbol, excluding artifact dates.

    Args:
        symbol: Ticker.
        bars: The symbol's daily bars in ascending date order.
        dead_dates: Market-wide non-session dates to exclude (see :func:`market_wide_dead_dates`).
        window: Number of trailing genuine sessions to measure.

    Returns:
        The symbol's :class:`LiquidityStat`.

    Raises:
        ValueError: If no live sessions remain after excluding ``dead_dates``.
    """
    live = [bar for bar in bars if bar.day not in dead_dates]
    if not live:
        raise ValueError(f"{symbol}: no live sessions after excluding artifact dates")
    tail = live[-window:]
    median = statistics.median(bar.traded_value for bar in tail)
    traded = sum(1 for bar in tail if bar.volume > 0)
    return LiquidityStat(
        symbol=symbol,
        window_start=tail[0].day,
        sessions=len(tail),
        median_traded_value=median,
        continuity_pct=100.0 * traded / len(tail),
    )


def run_gate(
    panel: Mapping[str, Sequence[DailyBar]],
    gate: LiquidityGate,
    *,
    max_alive: int = 1,
) -> list[LiquidityStat]:
    """Assess every symbol against ``gate``, most-liquid first.

    Args:
        panel: Mapping of symbol to ascending-date daily bars.
        gate: The pre-registered thresholds.
        max_alive: Passed to :func:`market_wide_dead_dates`.

    Returns:
        Per-symbol stats sorted by median traded value, descending.
    """
    dead = market_wide_dead_dates(panel, max_alive=max_alive)
    stats = [
        assess_symbol(symbol, bars, dead_dates=dead, window=gate.window)
        for symbol, bars in panel.items()
    ]
    stats.sort(key=lambda stat: stat.median_traded_value, reverse=True)
    return stats
