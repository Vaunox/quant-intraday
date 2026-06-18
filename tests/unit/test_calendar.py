"""Tests for the NSE calendar utility (P0.4)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from quant.core.calendar import (
    IST,
    CalendarError,
    NSECalendar,
    SessionPhase,
    load_nse_calendar,
)

# Construct known weekdays deterministically via the ISO calendar (no hand-computed
# weekday assumptions): day-of-week 1=Mon .. 5=Fri, 6=Sat, 7=Sun.
MONDAY = date.fromisocalendar(2026, 10, 1)
FRIDAY = date.fromisocalendar(2026, 10, 5)
SATURDAY = date.fromisocalendar(2026, 10, 6)
SUNDAY = date.fromisocalendar(2026, 10, 7)
NEXT_MONDAY = date.fromisocalendar(2026, 11, 1)

EMPTY = NSECalendar(holidays=frozenset())


def _ist(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


def test_weekday_is_trading_day() -> None:
    assert EMPTY.is_trading_day(MONDAY)
    assert not EMPTY.is_weekend(MONDAY)


def test_weekend_is_not_trading_day() -> None:
    assert EMPTY.is_weekend(SATURDAY)
    assert EMPTY.is_weekend(SUNDAY)
    assert not EMPTY.is_trading_day(SATURDAY)


def test_holiday_is_not_trading_day() -> None:
    cal = NSECalendar(holidays=frozenset({MONDAY}))
    assert cal.is_holiday(MONDAY)
    assert not cal.is_trading_day(MONDAY)


@pytest.mark.parametrize(
    ("hour", "minute", "phase"),
    [
        (8, 0, SessionPhase.CLOSED),
        (9, 0, SessionPhase.PRE_OPEN),
        (9, 14, SessionPhase.PRE_OPEN),
        (9, 15, SessionPhase.REGULAR),
        (12, 0, SessionPhase.REGULAR),
        (15, 29, SessionPhase.REGULAR),
        (15, 30, SessionPhase.CLOSED),
        (18, 0, SessionPhase.CLOSED),
    ],
)
def test_phase_at_boundaries(hour: int, minute: int, phase: SessionPhase) -> None:
    assert EMPTY.phase_at(_ist(MONDAY, hour, minute)) is phase


def test_phase_closed_on_weekend() -> None:
    assert EMPTY.phase_at(_ist(SATURDAY, 12, 0)) is SessionPhase.CLOSED


def test_phase_closed_on_holiday() -> None:
    cal = NSECalendar(holidays=frozenset({MONDAY}))
    assert cal.phase_at(_ist(MONDAY, 12, 0)) is SessionPhase.CLOSED


def test_is_open() -> None:
    assert EMPTY.is_open(_ist(MONDAY, 12, 0))
    assert not EMPTY.is_open(_ist(MONDAY, 16, 0))


def test_phase_converts_timezone() -> None:
    # 03:45 UTC == 09:15 IST -> regular session start.
    utc_open = datetime(MONDAY.year, MONDAY.month, MONDAY.day, 3, 45, tzinfo=UTC)
    assert EMPTY.phase_at(utc_open) is SessionPhase.REGULAR


def test_phase_requires_aware_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EMPTY.phase_at(datetime(2026, 1, 1, 10, 0))  # deliberately naive


def test_session_bounds() -> None:
    bounds = EMPTY.session_bounds(MONDAY)
    assert bounds is not None
    open_dt, close_dt = bounds
    assert (open_dt.hour, open_dt.minute) == (9, 15)
    assert (close_dt.hour, close_dt.minute) == (15, 30)
    assert open_dt.utcoffset() == timedelta(hours=5, minutes=30)
    assert EMPTY.session_bounds(SATURDAY) is None


def test_next_and_previous_trading_day_skip_weekend() -> None:
    assert EMPTY.next_trading_day(FRIDAY) == NEXT_MONDAY
    assert EMPTY.previous_trading_day(NEXT_MONDAY) == FRIDAY


def test_next_trading_day_skips_holiday() -> None:
    cal = NSECalendar(holidays=frozenset({NEXT_MONDAY}))
    assert cal.next_trading_day(FRIDAY) == date.fromisocalendar(2026, 11, 2)  # Tuesday


def test_session_phase_value() -> None:
    assert SessionPhase.REGULAR.value == "regular"


# --- loading -----------------------------------------------------------------


def test_load_real_calendar_has_seed_holiday() -> None:
    cal = load_nse_calendar(environ={})
    assert cal.is_holiday(date(2025, 1, 26))  # Republic Day, in the shipped seed
    assert not cal.is_trading_day(date(2025, 1, 26))


def test_load_from_custom_dir(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("holidays:\n  - 2026-03-10\n", encoding="utf-8")
    cal = load_nse_calendar(config_dir=tmp_path, environ={})
    assert cal.is_holiday(date(2026, 3, 10))
    assert not cal.is_holiday(date(2026, 3, 11))


def test_load_empty_file_means_no_holidays(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("", encoding="utf-8")
    assert load_nse_calendar(config_dir=tmp_path, environ={}).holidays == frozenset()


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CalendarError, match="not found"):
        load_nse_calendar(config_dir=tmp_path / "nope", environ={})


def test_load_rejects_non_mapping(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(CalendarError, match="mapping"):
        load_nse_calendar(config_dir=tmp_path, environ={})


def test_load_rejects_non_list_holidays(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("holidays: 5\n", encoding="utf-8")
    with pytest.raises(CalendarError, match="must be a list"):
        load_nse_calendar(config_dir=tmp_path, environ={})


def test_load_rejects_bad_date(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("holidays:\n  - not-a-date\n", encoding="utf-8")
    with pytest.raises(CalendarError, match="invalid date"):
        load_nse_calendar(config_dir=tmp_path, environ={})


def test_load_rejects_bad_entry_type(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.yaml").write_text("holidays:\n  - {x: 1}\n", encoding="utf-8")
    with pytest.raises(CalendarError, match="invalid holiday entry"):
        load_nse_calendar(config_dir=tmp_path, environ={})


def test_load_coerces_datetime_entry_to_date(tmp_path: Path) -> None:
    # A timestamped entry (YAML parses it as a datetime) is reduced to its date.
    (tmp_path / "nse_holidays.yaml").write_text(
        "holidays:\n  - 2026-03-10 09:00:00\n", encoding="utf-8"
    )
    cal = load_nse_calendar(config_dir=tmp_path, environ={})
    assert cal.is_holiday(date(2026, 3, 10))
