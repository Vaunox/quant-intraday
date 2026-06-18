"""Authoritative NSE trading-calendar / session utility (all times in IST).

Every part of the system that asks "is the market open?", "is this a trading day?",
or "what session phase is it?" goes through here, so the answer is consistent in
backtest, live, scheduling, and hygiene (Layer 1 hygiene; Layer 5 scheduler).

Exchange session times are fixed facts and live here as named constants
(Ground Rule 2). The holiday list is reference data loaded from
``config/nse_holidays.yaml`` (or injected), because it changes every year.

Note: the *self*-square-off time (~15:15, before the broker's auto-square-off) is an
operational choice and lives in config (``execution.self_square_off_time``); this
module models the exchange's own session phases.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from quant.core.config import discover_config_dir

#: India Standard Time (UTC+05:30, no DST).
IST = ZoneInfo("Asia/Kolkata")

#: Pre-open session start (09:00 IST).
PRE_OPEN_START = time(9, 0)
#: Regular session start / pre-open end (09:15 IST).
MARKET_OPEN = time(9, 15)
#: Regular session end (15:30 IST).
MARKET_CLOSE = time(15, 30)

# date.weekday(): Monday=0 .. Saturday=5, Sunday=6.
_WEEKEND = frozenset({5, 6})


class CalendarError(RuntimeError):
    """Raised when the holiday calendar cannot be located or parsed."""


class SessionPhase(str, Enum):
    """A point in the NSE trading day."""

    CLOSED = "closed"
    PRE_OPEN = "pre_open"
    REGULAR = "regular"


@dataclass(frozen=True)
class NSECalendar:
    """Trading-day and session classification for the NSE, in IST.

    Args:
        holidays: Full-day market-closure dates.
        tz: Session timezone (IST; injectable only for testing).
    """

    holidays: frozenset[date]
    tz: ZoneInfo = field(default=IST)

    def is_holiday(self, day: date) -> bool:
        """Return whether ``day`` is a listed full-day market holiday."""
        return day in self.holidays

    def is_weekend(self, day: date) -> bool:
        """Return whether ``day`` falls on a Saturday or Sunday."""
        return day.weekday() in _WEEKEND

    def is_trading_day(self, day: date) -> bool:
        """Return whether the market trades on ``day`` (weekday and not a holiday)."""
        return not self.is_weekend(day) and not self.is_holiday(day)

    def session_open(self, day: date) -> datetime:
        """Return the regular-session open instant (09:15 IST) on ``day``."""
        return datetime.combine(day, MARKET_OPEN, tzinfo=self.tz)

    def session_close(self, day: date) -> datetime:
        """Return the regular-session close instant (15:30 IST) on ``day``."""
        return datetime.combine(day, MARKET_CLOSE, tzinfo=self.tz)

    def session_bounds(self, day: date) -> tuple[datetime, datetime] | None:
        """Return ``(open, close)`` for a trading day, or ``None`` if closed."""
        if not self.is_trading_day(day):
            return None
        return self.session_open(day), self.session_close(day)

    def phase_at(self, moment: datetime) -> SessionPhase:
        """Classify a timezone-aware instant into its NSE session phase.

        Args:
            moment: A timezone-aware datetime (converted to IST internally).

        Raises:
            ValueError: If ``moment`` is naive (no timezone).
        """
        if moment.tzinfo is None:
            raise ValueError("phase_at requires a timezone-aware datetime")
        local = moment.astimezone(self.tz)
        if not self.is_trading_day(local.date()):
            return SessionPhase.CLOSED
        wall = local.time()
        if PRE_OPEN_START <= wall < MARKET_OPEN:
            return SessionPhase.PRE_OPEN
        if MARKET_OPEN <= wall < MARKET_CLOSE:
            return SessionPhase.REGULAR
        return SessionPhase.CLOSED

    def is_open(self, moment: datetime) -> bool:
        """Return whether the regular session is live at ``moment``."""
        return self.phase_at(moment) is SessionPhase.REGULAR

    def next_trading_day(self, day: date) -> date:
        """Return the first trading day strictly after ``day``."""
        candidate = day + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def previous_trading_day(self, day: date) -> date:
        """Return the last trading day strictly before ``day``."""
        candidate = day - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate


def _coerce_date(value: object, source: Path) -> date:
    """Coerce a YAML holiday entry (date or ISO string) to a :class:`date`."""
    if isinstance(value, datetime):  # must precede `date` (datetime subclasses date)
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CalendarError(f"{source}: invalid date {value!r}") from exc
    raise CalendarError(f"{source}: invalid holiday entry {value!r}")


def load_nse_calendar(
    config_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> NSECalendar:
    """Load the NSE calendar from ``nse_holidays.yaml``.

    Args:
        config_dir: Directory holding ``nse_holidays.yaml`` (defaults to discovery).
        environ: Environment mapping (injected for tests); defaults to ``os.environ``.

    Returns:
        An :class:`NSECalendar` populated with the configured holidays.

    Raises:
        CalendarError: If the holiday file is missing or malformed.
    """
    environ = os.environ if environ is None else environ
    directory = Path(config_dir) if config_dir is not None else discover_config_dir(environ)
    path = directory / "nse_holidays.yaml"
    if not path.is_file():
        raise CalendarError(f"NSE holiday file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise CalendarError(f"{path} must contain a mapping at the top level")
    raw = data.get("holidays") or []
    if not isinstance(raw, list):
        raise CalendarError(f"{path}: 'holidays' must be a list")
    holidays = frozenset(_coerce_date(item, path) for item in raw)
    return NSECalendar(holidays=holidays)
