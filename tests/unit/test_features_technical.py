"""Tests for TA-Lib technical features (P1.7).

The wrappers are thin (convert close -> float64 array -> TA-Lib -> Series), so the tests
assert the pass-through equals TA-Lib directly plus the Series wiring (index, name, NaN
warmup, validation) and basic value ranges.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import talib

from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.data.features.technical import bollinger_percent_b, macd_histogram, rsi
from tests.unit.hygiene_fakes import IST

_BASE = datetime(2024, 6, 3, 9, 15, tzinfo=IST)


def _bars(n: int = 60) -> pd.DataFrame:
    """n bars with a deterministic wave so indicators have signal."""
    bars = []
    for i in range(n):
        close = 100.0 + 5.0 * np.sin(i / 5.0) + (i % 3)
        bars.append(
            Bar("X", _BASE + timedelta(minutes=i), close, close + 0.5, close - 0.5, close, 1000 + i)
        )
    return bars_to_frame(bars)


def test_rsi_matches_talib_and_is_bounded() -> None:
    bars = _bars()
    result = rsi(bars, 14)
    expected = talib.RSI(bars["close"].to_numpy(dtype="float64"), timeperiod=14)
    np.testing.assert_allclose(result.to_numpy(), expected, equal_nan=True)
    assert result.name == "rsi_14"
    valid = result.dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_rsi_rejects_bad_period() -> None:
    with pytest.raises(ValueError, match="period"):
        rsi(_bars(), 1)


def test_macd_histogram_matches_talib() -> None:
    bars = _bars()
    result = macd_histogram(bars, fast=12, slow=26, signal=9)
    _, _, expected = talib.MACD(
        bars["close"].to_numpy(dtype="float64"), fastperiod=12, slowperiod=26, signalperiod=9
    )
    np.testing.assert_allclose(result.to_numpy(), expected, equal_nan=True)
    assert result.name == "macd_hist"


def test_macd_rejects_fast_not_below_slow() -> None:
    with pytest.raises(ValueError, match="fast"):
        macd_histogram(_bars(), fast=26, slow=12, signal=9)


def test_macd_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError, match="positive"):
        macd_histogram(_bars(), fast=12, slow=26, signal=0)


def test_bollinger_percent_b_definition() -> None:
    bars = _bars()
    result = bollinger_percent_b(bars, period=20, num_std=2.0)
    close = bars["close"].to_numpy(dtype="float64")
    upper, _, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
    expected = (close - lower) / (upper - lower)
    np.testing.assert_allclose(result.to_numpy(), expected, equal_nan=True)
    assert result.name == "bbands_percent_b"


def test_bollinger_rejects_bad_args() -> None:
    with pytest.raises(ValueError, match="num_std"):
        bollinger_percent_b(_bars(), period=20, num_std=0.0)


def test_bollinger_rejects_short_period() -> None:
    with pytest.raises(ValueError, match="period"):
        bollinger_percent_b(_bars(), period=1, num_std=2.0)
