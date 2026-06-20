"""Data-quality report value objects (Layer 1 — the data-quality dashboard, P1.9).

Deep Dive #1: *"a data-quality dashboard (gaps, bad-tick counts, feed latency, coverage)."*
These immutable carriers hold the assessed health of a dataset; :class:`DataQualityDashboard`
(in :mod:`quant.data.quality.dashboard`) builds them, and :meth:`DataQualityReport.render`
turns one into a human-readable dashboard.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CoverageStats:
    """How much of the expected data is present for one symbol over a window.

    Coverage is measured at the *session* level (trading days present vs expected per the
    NSE calendar); bar-level holes are reported separately as gaps.
    """

    symbol: str
    expected_sessions: int  # trading days in the requested window (calendar)
    observed_sessions: int  # distinct days with at least one bar
    observed_bars: int  # bars present in the window
    first_bar: datetime | None  # earliest bar timestamp in the window
    last_bar: datetime | None  # latest bar timestamp in the window

    @property
    def session_coverage(self) -> float:
        """Fraction of expected trading days that have data (1.0 if none expected)."""
        if self.expected_sessions == 0:
            return 1.0
        return self.observed_sessions / self.expected_sessions

    @property
    def is_complete(self) -> bool:
        """Whether every expected trading day has at least one bar."""
        return self.observed_sessions >= self.expected_sessions


@dataclass(frozen=True, slots=True)
class SymbolQuality:
    """The assessed data quality for a single symbol."""

    symbol: str
    coverage: CoverageStats
    intraday_gaps: int  # count of intraday spacing gaps (P1.5 GapDetector)
    missing_days: int  # trading days inside the data span with no bars
    bad_ticks: int  # bars removed by the bad-tick filter (P1.5)

    @property
    def has_issues(self) -> bool:
        """Whether any quality problem was found (incomplete coverage, gaps, or bad ticks)."""
        return (
            not self.coverage.is_complete
            or self.intraday_gaps > 0
            or self.missing_days > 0
            or self.bad_ticks > 0
        )


@dataclass(frozen=True, slots=True)
class FeedLatencyStats:
    """Summary of live-feed latency samples (event-to-receipt delay, in seconds)."""

    samples: int
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    max_seconds: float


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """The aggregate data-quality report across symbols, plus optional feed latency."""

    symbols: tuple[SymbolQuality, ...]
    feed_latency: FeedLatencyStats | None = None

    @property
    def symbols_with_issues(self) -> tuple[SymbolQuality, ...]:
        """The symbols that have at least one quality issue."""
        return tuple(symbol for symbol in self.symbols if symbol.has_issues)

    @property
    def ok(self) -> bool:
        """Whether every symbol is clean (no issues)."""
        return not self.symbols_with_issues

    @property
    def total_intraday_gaps(self) -> int:
        """Total intraday gaps across all symbols."""
        return sum(symbol.intraday_gaps for symbol in self.symbols)

    @property
    def total_missing_days(self) -> int:
        """Total missing trading days across all symbols."""
        return sum(symbol.missing_days for symbol in self.symbols)

    @property
    def total_bad_ticks(self) -> int:
        """Total bad ticks across all symbols."""
        return sum(symbol.bad_ticks for symbol in self.symbols)

    def render(self) -> str:
        """Render the report as a plain-text dashboard (one row per symbol + summary)."""
        lines = [
            "Data Quality Report",
            (
                f"symbols={len(self.symbols)} with_issues={len(self.symbols_with_issues)} "
                f"intraday_gaps={self.total_intraday_gaps} "
                f"missing_days={self.total_missing_days} bad_ticks={self.total_bad_ticks}"
            ),
            f"{'symbol':<14}{'sessions':>10}{'bars':>8}{'gaps':>6}"
            f"{'missdays':>9}{'badticks':>9}  status",
        ]
        for symbol in self.symbols:
            sessions = f"{symbol.coverage.observed_sessions}/{symbol.coverage.expected_sessions}"
            status = "ISSUES" if symbol.has_issues else "ok"
            lines.append(
                f"{symbol.symbol:<14}{sessions:>10}{symbol.coverage.observed_bars:>8}"
                f"{symbol.intraday_gaps:>6}{symbol.missing_days:>9}{symbol.bad_ticks:>9}  {status}"
            )
        if self.feed_latency is not None:
            latency = self.feed_latency
            lines.append(
                f"feed latency: n={latency.samples} mean={latency.mean_seconds:.3f}s "
                f"p50={latency.p50_seconds:.3f}s p95={latency.p95_seconds:.3f}s "
                f"max={latency.max_seconds:.3f}s"
            )
        return "\n".join(lines)
