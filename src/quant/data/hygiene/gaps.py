"""Continuity & gap detection (Deep Dive #1 §1.3.5).

*"Missing minute bars are common. Decide a policy (forward-fill vs leave-gap vs flag)
and apply it identically in research and live. Alert on unexpected gaps live."*

This module is the **detection** half (the fill/flag policy is applied later, in the
feature path, so research and live share one implementation). It reports two kinds of
hole, calendar-aware so expected closures are never flagged:

* **Intraday gaps** — within a single trading day, consecutive bars spaced more than one
  interval apart (the overnight jump between days is expected and never reported).
* **Missing trading days** — trading days inside the data's span (per the NSE calendar)
  that hold no bars at all.

The detector is convention-agnostic about whether bars are open- or close-labelled: it
checks the *spacing* between observed bars rather than matching a fixed expected grid.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise

import pandas as pd

from quant.core.calendar import IST, NSECalendar
from quant.core.logging import get_logger
from quant.data.store import serde

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Gap:
    """An intraday run of missing bars between two observed bars on the same day."""

    symbol: str
    previous: datetime  # last bar before the gap
    following: datetime  # first bar after the gap
    missing_bars: int  # expected bars absent between them


@dataclass(frozen=True, slots=True)
class GapReport:
    """All detected discontinuities for one symbol over the span of its bars."""

    symbol: str
    intraday_gaps: tuple[Gap, ...]
    missing_days: tuple[date, ...]

    @property
    def has_gaps(self) -> bool:
        """Whether any intraday gap or missing trading day was found."""
        return bool(self.intraday_gaps) or bool(self.missing_days)


class GapDetector:
    """Detects intraday gaps and missing trading days in a symbol's bars."""

    def __init__(self, calendar: NSECalendar, *, interval_minutes: int) -> None:
        """Build the detector.

        Args:
            calendar: NSE calendar (which days are trading days).
            interval_minutes: Expected spacing between consecutive intraday bars (> 0).

        Raises:
            ValueError: If ``interval_minutes`` is not positive.
        """
        if interval_minutes <= 0:
            raise ValueError(f"interval_minutes must be positive, got {interval_minutes!r}")
        self._calendar = calendar
        self._interval = interval_minutes

    def detect(self, symbol: str, bars: pd.DataFrame) -> GapReport:
        """Return the gap report for ``symbol``'s bars (empty frame → no gaps).

        Raises:
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        if frame.empty:
            return GapReport(symbol=symbol, intraday_gaps=(), missing_days=())
        times = list(frame[serde.TIME_COLUMN].dt.tz_convert(IST))
        intraday_gaps = self._intraday_gaps(symbol, times)
        missing_days = self._missing_days(times)
        if intraday_gaps or missing_days:
            _logger.warning(
                "data gaps detected",
                extra={
                    "symbol": symbol,
                    "intraday_gaps": len(intraday_gaps),
                    "missing_days": len(missing_days),
                },
            )
        return GapReport(
            symbol=symbol, intraday_gaps=tuple(intraday_gaps), missing_days=tuple(missing_days)
        )

    def _intraday_gaps(self, symbol: str, times: Sequence[datetime]) -> list[Gap]:
        """Find same-day consecutive bars spaced more than one interval apart."""
        gaps: list[Gap] = []
        for previous, following in pairwise(times):
            if previous.date() != following.date():
                continue  # overnight boundary — an expected gap, never flagged
            step_minutes = (following - previous).total_seconds() / 60.0
            missing = round(step_minutes / self._interval) - 1
            if missing > 0:
                gaps.append(
                    Gap(
                        symbol=symbol,
                        previous=previous,
                        following=following,
                        missing_bars=missing,
                    )
                )
        return gaps

    def _missing_days(self, times: Sequence[datetime]) -> list[date]:
        """Find trading days within the data span that hold no bars."""
        present = {moment.date() for moment in times}
        day = min(present)
        last = max(present)
        missing: list[date] = []
        while day <= last:
            if self._calendar.is_trading_day(day) and day not in present:
                missing.append(day)
            day += timedelta(days=1)
        return missing
