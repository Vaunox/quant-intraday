"""Tests for the intraday VWAP-deviation feature (P1.6)."""

from datetime import date

import pandas as pd
import pytest

from quant.data.features.vwap import intraday_vwap, vwap_deviation
from tests.unit.hygiene_fakes import at, bar, frame, good

D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)


def test_intraday_vwap_is_cumulative_and_resets_per_day() -> None:
    # good() makes typical price == close. Day 1: 100@10, 110@30 -> VWAP 100 then 107.5.
    bars = frame(
        [
            good("X", at(D1, 9, 15), 100.0, vol=10),
            good("X", at(D1, 9, 16), 110.0, vol=30),
            good("X", at(D2, 9, 15), 200.0, vol=5),  # new session -> resets
        ]
    )
    vwap = intraday_vwap(bars)
    assert vwap.iloc[0] == pytest.approx(100.0)
    assert vwap.iloc[1] == pytest.approx((100 * 10 + 110 * 30) / 40)  # 107.5
    assert vwap.iloc[2] == pytest.approx(200.0)  # day 2 starts fresh


def test_vwap_deviation_sign_and_value() -> None:
    bars = frame([good("X", at(D1, 9, 15), 100.0, vol=10), good("X", at(D1, 9, 16), 110.0, vol=30)])
    dev = vwap_deviation(bars)
    assert dev.name == "vwap_dev"
    assert dev.iloc[0] == pytest.approx(0.0)  # first bar: close == vwap
    assert dev.iloc[1] == pytest.approx((110 - 107.5) / 107.5)  # above VWAP -> positive


def test_zero_leading_volume_is_nan_not_divzero() -> None:
    bars = frame(
        [
            bar("X", at(D1, 9, 15), o=100, h=100, lo=100, c=100, v=0),  # cum vol 0
            good("X", at(D1, 9, 16), 110.0, vol=10),
        ]
    )
    vwap = intraday_vwap(bars)
    assert pd.isna(vwap.iloc[0])  # divide-by-zero avoided
    assert vwap.iloc[1] == pytest.approx(110.0)  # once volume arrives


def test_vwap_is_causal_under_append() -> None:
    short = intraday_vwap(frame([good("X", at(D1, 9, 15), 100.0, vol=10)]))
    long = intraday_vwap(
        frame([good("X", at(D1, 9, 15), 100.0, vol=10), good("X", at(D1, 9, 16), 110.0, vol=30)])
    )
    assert long.iloc[0] == pytest.approx(short.iloc[0])  # earlier VWAP unchanged
