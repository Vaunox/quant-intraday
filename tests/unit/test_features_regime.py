"""Tests for regime features (P1.7)."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.data.features.regime import trend_strength, volatility_regime
from quant.data.features.volatility import realized_volatility
from tests.unit.hygiene_fakes import IST

_BASE = datetime(2024, 6, 3, 9, 15, tzinfo=IST)


def _bars(closes: list[float]) -> pd.DataFrame:
    return bars_to_frame(
        [
            Bar("X", _BASE + timedelta(minutes=i), c, c + 0.5, c - 0.5, c, 1000)
            for i, c in enumerate(closes)
        ]
    )


def test_volatility_regime_is_vol_over_trailing_median() -> None:
    # Calm then a volatility burst -> recent vol above its trailing median (ratio > 1).
    closes = [100.0 + 0.1 * (i % 2) for i in range(20)] + [100.0 + 8.0 * (i % 2) for i in range(8)]
    bars = _bars(closes)
    regime = volatility_regime(bars, vol_window=5, lookback=10)
    rvol = realized_volatility(bars, 5)
    median = rvol.rolling(10).median()
    expected = (rvol / median.where(median != 0)).iloc[-1]
    assert regime.iloc[-1] == pytest.approx(expected)
    assert regime.iloc[-1] > 1.0  # burst is a high-vol regime
    assert regime.name == "vol_regime"


def test_trend_strength_positive_in_uptrend() -> None:
    bars = _bars([100.0 + i for i in range(20)])  # steady uptrend
    trend = trend_strength(bars, window=5)
    assert trend.iloc[-1] > 0.0  # close above its trailing mean
    # Matches the close-vs-mean z-score definition.
    close = bars["close"]
    expected = ((close - close.rolling(5).mean()) / close.rolling(5).std()).iloc[-1]
    assert trend.iloc[-1] == pytest.approx(expected)
    assert trend.name == "trend_strength"


def test_trend_strength_is_causal() -> None:
    closes = [100.0, 101, 99, 103, 98, 105, 97, 108]
    full = trend_strength(_bars(closes), window=3)
    prefix = trend_strength(_bars(closes[:5]), window=3)
    np.testing.assert_allclose(full.to_numpy()[:5], prefix.to_numpy(), equal_nan=True)


@pytest.mark.parametrize(
    "call",
    [
        lambda b: volatility_regime(b, vol_window=1, lookback=10),
        lambda b: volatility_regime(b, vol_window=5, lookback=1),
        lambda b: trend_strength(b, window=1),
    ],
)
def test_regime_rejects_bad_windows(call: object) -> None:
    with pytest.raises(ValueError):
        call(_bars([100.0, 101.0, 102.0]))  # type: ignore[operator]
