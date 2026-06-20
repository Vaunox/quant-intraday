"""Tests for continuity & gap detection (P1.5) — intraday gaps + missing trading days."""

from datetime import date

import pytest

from quant.core.calendar import NSECalendar
from quant.data.hygiene.gaps import GapDetector
from quant.data.store.errors import SchemaError
from tests.unit.hygiene_fakes import at, frame, good

# Mon/Tue/Wed, all weekdays.
D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
D3 = date(2024, 6, 5)
NO_HOLIDAYS = NSECalendar(frozenset())


def _detector(interval: int = 1, calendar: NSECalendar = NO_HOLIDAYS) -> GapDetector:
    return GapDetector(calendar, interval_minutes=interval)


def test_intraday_gap_detected() -> None:
    bars = frame(
        [
            good("X", at(D1, 9, 15), 100),
            good("X", at(D1, 9, 16), 100),
            good("X", at(D1, 9, 18), 100),
        ]
    )
    report = _detector().detect("X", bars)
    assert len(report.intraday_gaps) == 1
    gap = report.intraday_gaps[0]
    assert gap.previous == at(D1, 9, 16)
    assert gap.following == at(D1, 9, 18)
    assert gap.missing_bars == 1  # the 09:17 bar
    assert report.missing_days == ()


def test_overnight_boundary_is_not_a_gap() -> None:
    # Last bar of D1 to first bar of D3 is a cross-day jump — never flagged intraday.
    bars = frame([good("X", at(D1, 15, 29), 100), good("X", at(D3, 9, 15), 100)])
    report = _detector().detect("X", bars)
    assert report.intraday_gaps == ()


def test_missing_trading_day_detected() -> None:
    bars = frame([good("X", at(D1, 9, 15), 100), good("X", at(D3, 9, 15), 100)])
    report = _detector().detect("X", bars)
    assert report.missing_days == (D2,)  # a trading day inside the span with no bars
    assert report.has_gaps


def test_holiday_in_span_is_not_missing() -> None:
    holiday_cal = NSECalendar(frozenset({D2}))  # D2 is a holiday
    bars = frame([good("X", at(D1, 9, 15), 100), good("X", at(D3, 9, 15), 100)])
    report = GapDetector(holiday_cal, interval_minutes=1).detect("X", bars)
    assert report.missing_days == ()  # closed day, correctly not flagged


def test_weekend_in_span_is_not_missing() -> None:
    friday = date(2024, 5, 31)
    monday = date(2024, 6, 3)
    bars = frame([good("X", at(friday, 9, 15), 100), good("X", at(monday, 9, 15), 100)])
    report = _detector().detect("X", bars)
    assert report.missing_days == ()  # Sat/Sun are not trading days


def test_contiguous_bars_have_no_gaps() -> None:
    bars = frame([good("X", at(D1, 9, 15 + i), 100) for i in range(5)])
    report = _detector().detect("X", bars)
    assert not report.has_gaps


def test_interval_aware_spacing() -> None:
    # 15-minute bars: 09:15 -> 09:30 is one step (ok); 09:30 -> 10:00 misses one (09:45).
    bars = frame(
        [
            good("X", at(D1, 9, 15), 100),
            good("X", at(D1, 9, 30), 100),
            good("X", at(D1, 10, 0), 100),
        ]
    )
    report = _detector(interval=15).detect("X", bars)
    assert [g.missing_bars for g in report.intraday_gaps] == [1]


def test_non_positive_interval_rejected() -> None:
    with pytest.raises(ValueError, match="interval_minutes"):
        GapDetector(NO_HOLIDAYS, interval_minutes=0)


def test_empty_frame_has_no_gaps() -> None:
    report = _detector().detect("X", frame([]))
    assert not report.has_gaps


def test_bad_schema_rejected() -> None:
    bars = frame([good("X", at(D1, 9, 15), 100)]).drop(columns=["close"])
    with pytest.raises(SchemaError):
        _detector().detect("X", bars)
