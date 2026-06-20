"""Tests for cyclical time-of-day features (P1.7)."""

import math
from datetime import date

import pytest

from quant.core.calendar import NSECalendar
from quant.data.features.temporal import TEMPORAL_COLUMNS, time_of_day_features
from tests.unit.hygiene_fakes import at, frame, good

MONDAY = date(2024, 6, 3)  # weekday 0
CALENDAR = NSECalendar(frozenset())


def test_columns_and_cyclic_unit_circle() -> None:
    bars = frame([good("X", at(MONDAY, 9, 15), 100), good("X", at(MONDAY, 11, 15), 100)])
    feats = time_of_day_features(bars, CALENDAR)
    assert tuple(feats.columns) == TEMPORAL_COLUMNS
    # sin^2 + cos^2 == 1 for both cyclic encodings.
    assert (feats["minute_of_day_sin"] ** 2 + feats["minute_of_day_cos"] ** 2).round(9).eq(1).all()
    assert (feats["day_of_week_sin"] ** 2 + feats["day_of_week_cos"] ** 2).round(9).eq(1).all()


def test_minute_of_day_encoding() -> None:
    bars = frame([good("X", at(MONDAY, 9, 15), 100)])  # 09:15 -> minute 555 of 1440
    feats = time_of_day_features(bars, CALENDAR)
    angle = 2.0 * math.pi * 555 / 1440
    assert feats["minute_of_day_sin"].iloc[0] == pytest.approx(math.sin(angle))
    assert feats["minute_of_day_cos"].iloc[0] == pytest.approx(math.cos(angle))


def test_day_of_week_encoding_monday() -> None:
    feats = time_of_day_features(frame([good("X", at(MONDAY, 9, 15), 100)]), CALENDAR)
    assert feats["day_of_week_sin"].iloc[0] == pytest.approx(0.0)  # sin(0)
    assert feats["day_of_week_cos"].iloc[0] == pytest.approx(1.0)  # cos(0)


def test_session_fractions_span_open_to_close() -> None:
    bars = frame(
        [
            good("X", at(MONDAY, 9, 15), 100),  # session open
            good("X", at(MONDAY, 15, 30), 100),  # session close
        ]
    )
    feats = time_of_day_features(bars, CALENDAR)
    assert feats["time_since_open"].iloc[0] == pytest.approx(0.0)
    assert feats["time_to_close"].iloc[0] == pytest.approx(1.0)
    assert feats["time_since_open"].iloc[1] == pytest.approx(1.0)
    assert feats["time_to_close"].iloc[1] == pytest.approx(0.0)


def test_is_pure_function_of_timestamp() -> None:
    bars = frame([good("X", at(MONDAY, 10, 0), 100)])
    first = time_of_day_features(bars, CALENDAR)
    second = time_of_day_features(bars, CALENDAR)
    assert first.equals(second)
