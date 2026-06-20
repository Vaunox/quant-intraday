"""Tests for volatility features (P1.6) — checked against independent computations."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.data.features.volatility import atr, parkinson_volatility, realized_volatility
from tests.unit.hygiene_fakes import at, bar, frame, good

D1 = date(2024, 6, 3)


def test_realized_volatility_matches_sample_std() -> None:
    closes = [100.0, 102.0, 101.0, 104.0]
    bars = frame([good("X", at(D1, 9, 15 + i), c) for i, c in enumerate(closes)])
    result = realized_volatility(bars, 3)
    # Last value = sample std (ddof=1) of the three most recent 1-bar log returns.
    returns = np.diff(np.log(closes))
    assert result.iloc[-1] == pytest.approx(float(np.std(returns[-3:], ddof=1)))
    assert pd.isna(result.iloc[0])  # warmup
    assert result.name == "rvol_3"


def test_atr_true_range_average() -> None:
    bars = frame(
        [
            bar("X", at(D1, 9, 15), o=10, h=11, lo=9, c=10, v=1),  # TR = 2 (no prev close)
            bar("X", at(D1, 9, 16), o=10, h=12, lo=10, c=11, v=1),  # TR = max(2, 2, 0) = 2
            bar("X", at(D1, 9, 17), o=11, h=13, lo=8, c=9, v=1),  # TR = max(5, 2, 3) = 5
        ]
    )
    result = atr(bars, 2)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 2.0  # mean(2, 2)
    assert result.iloc[2] == 3.5  # mean(2, 5)


def test_parkinson_uses_high_low_range() -> None:
    bars = frame([bar("X", at(D1, 9, 15 + i), o=105, h=110, lo=100, c=105, v=1) for i in range(3)])
    result = parkinson_volatility(bars, 2)
    expected = float(np.sqrt((1.0 / (4.0 * np.log(2.0))) * np.log(1.1) ** 2))
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == pytest.approx(expected)
    assert (result.dropna() >= 0).all()  # volatility is non-negative


@pytest.mark.parametrize("func", [realized_volatility, parkinson_volatility, atr])
def test_window_must_exceed_one(func: object) -> None:
    bars = frame([good("X", at(D1, 9, 15), 100)])
    with pytest.raises(ValueError, match="window"):
        func(bars, 1)  # type: ignore[operator]
