"""The data-quality dashboard (Layer 1, P1.9) — visibility into data health.

Composes the P1.5 hygiene jobs (gap detection, bad-tick filtering) with session-level
coverage (from the NSE calendar) and live-feed latency into one
:class:`~quant.data.quality.report.DataQualityReport`. It surfaces — per symbol — how much
of the expected data is present, where the holes are, how many erroneous prints were
removed, and how laggy the feed is.

Pure over its inputs (it reads bars, never writes), and broker/store-agnostic: it takes
in-memory bars per symbol (the caller fetches them through the ``Repository``).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from quant.core.calendar import IST, NSECalendar, load_nse_calendar
from quant.core.config import Config
from quant.core.logging import get_logger
from quant.data.hygiene.bad_ticks import BadTickFilter
from quant.data.hygiene.gaps import GapDetector
from quant.data.quality.report import (
    CoverageStats,
    DataQualityReport,
    FeedLatencyStats,
    SymbolQuality,
)
from quant.data.store import serde

_logger = get_logger(__name__)


class DataQualityDashboard:
    """Assesses dataset health across symbols, composing the hygiene jobs + coverage."""

    def __init__(
        self,
        calendar: NSECalendar,
        gap_detector: GapDetector,
        bad_tick_filter: BadTickFilter,
    ) -> None:
        """Build the dashboard from a calendar and the (config-driven) hygiene jobs."""
        self._calendar = calendar
        self._gap_detector = gap_detector
        self._bad_tick_filter = bad_tick_filter

    def assess(
        self,
        bars_by_symbol: Mapping[str, pd.DataFrame],
        *,
        start: datetime,
        end: datetime,
        latency_samples: Sequence[float] | None = None,
    ) -> DataQualityReport:
        """Assess data quality for each symbol over ``[start, end]``.

        Args:
            bars_by_symbol: Raw bars per symbol (assessed as-is, so issues surface).
            start: Inclusive window start (tz-aware IST).
            end: Inclusive window end (tz-aware IST).
            latency_samples: Optional live-feed latency samples in seconds.

        Returns:
            A :class:`DataQualityReport` (symbols sorted) with optional feed-latency stats.

        Raises:
            ValueError: If ``start``/``end`` are naive or ``start`` is after ``end``.
            SchemaError: If any bars frame is not in the canonical schema.
        """
        _require_aware(start, "start")
        _require_aware(end, "end")
        if start > end:
            raise ValueError(f"start {start.isoformat()} is after end {end.isoformat()}")

        results = [
            self._assess_symbol(symbol, bars_by_symbol[symbol], start, end)
            for symbol in sorted(bars_by_symbol)
        ]
        report = DataQualityReport(
            symbols=tuple(results), feed_latency=summarize_feed_latency(latency_samples)
        )
        _logger.info(
            "data-quality assessed",
            extra={
                "symbols": len(results),
                "with_issues": len(report.symbols_with_issues),
                "bad_ticks": report.total_bad_ticks,
                "intraday_gaps": report.total_intraday_gaps,
                "missing_days": report.total_missing_days,
            },
        )
        return report

    def _assess_symbol(
        self, symbol: str, bars: pd.DataFrame, start: datetime, end: datetime
    ) -> SymbolQuality:
        """Assess one symbol's bars (restricted to the window) on every quality axis."""
        window = serde.restrict_to_range(serde.ensure_bars_schema(bars), start, end)
        coverage = self._coverage(symbol, window, start, end)
        gaps = self._gap_detector.detect(symbol, window)
        cleaned = self._bad_tick_filter.filter(symbol, window)
        return SymbolQuality(
            symbol=symbol,
            coverage=coverage,
            intraday_gaps=len(gaps.intraday_gaps),
            missing_days=len(gaps.missing_days),
            bad_ticks=cleaned.removed,
        )

    def _coverage(
        self, symbol: str, window: pd.DataFrame, start: datetime, end: datetime
    ) -> CoverageStats:
        """Compute session-level coverage of ``window`` against the expected trading days."""
        expected = self._expected_sessions(start, end)
        if window.empty:
            return CoverageStats(symbol, expected, 0, 0, None, None)
        times = window[serde.TIME_COLUMN]
        observed_days = times.dt.tz_convert(IST).dt.date.nunique()
        return CoverageStats(
            symbol=symbol,
            expected_sessions=expected,
            observed_sessions=int(observed_days),
            observed_bars=len(window),
            first_bar=times.iloc[0].to_pydatetime(),
            last_bar=times.iloc[-1].to_pydatetime(),
        )

    def _expected_sessions(self, start: datetime, end: datetime) -> int:
        """Count NSE trading days in ``[start, end]`` (inclusive), in IST."""
        day = start.astimezone(IST).date()
        last = end.astimezone(IST).date()
        sessions = 0
        while day <= last:
            if self._calendar.is_trading_day(day):
                sessions += 1
            day += timedelta(days=1)
        return sessions


def summarize_feed_latency(samples: Sequence[float] | None) -> FeedLatencyStats | None:
    """Summarize live-feed latency samples (seconds) into stats, or ``None`` if no samples.

    Latency is the event-to-receipt delay per tick (the live stream, P1.2, is where the
    samples are recorded); this reports mean / p50 / p95 / max so a laggy feed is visible.
    """
    if not samples:
        return None
    values = np.asarray([float(sample) for sample in samples], dtype="float64")
    return FeedLatencyStats(
        samples=int(values.size),
        mean_seconds=float(values.mean()),
        p50_seconds=float(np.percentile(values, 50)),
        p95_seconds=float(np.percentile(values, 95)),
        max_seconds=float(values.max()),
    )


def create_data_quality_dashboard(
    config: Config, calendar: NSECalendar | None = None
) -> DataQualityDashboard:
    """Build a dashboard from configuration (interval + bad-tick threshold) and the calendar.

    The gap detector's interval comes from ``market.bar_interval_minutes`` and the bad-tick
    threshold from ``hygiene.bad_tick_max_move_pct`` (Ground Rule 2). The calendar defaults
    to the configured NSE holiday calendar.
    """
    resolved_calendar = calendar if calendar is not None else load_nse_calendar()
    gap_detector = GapDetector(
        resolved_calendar, interval_minutes=config.market.bar_interval_minutes
    )
    bad_tick_filter = BadTickFilter.from_config(config.hygiene)
    return DataQualityDashboard(resolved_calendar, gap_detector, bad_tick_filter)


def _require_aware(moment: datetime, label: str) -> None:
    """Raise if ``moment`` is timezone-naive (the system's instants are always IST)."""
    if moment.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware (IST), got naive {moment.isoformat()}")
