"""Correctness tests for the Phase-3X price factors on hand-computed panels (P3X.2)."""

import numpy as np
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.data.store import serde
from quant.research.factors import (
    amihud_illiquidity,
    low_volatility,
    momentum_12_1,
    residual_momentum,
    short_term_reversal,
)


def _bars(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """Build a canonical daily bars frame for one symbol from a list of closes."""
    n = len(closes)
    close = np.asarray(closes, dtype="float64")
    vol = np.asarray(volumes if volumes is not None else [1_000_000.0] * n, dtype="float64")
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-01", periods=n, freq="B", tz=IST),
            "symbol": "X",
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": vol.round().astype("int64"),
        }
    )
    return serde.ensure_bars_schema(frame)


# A clean geometric path: close[i] = 100 * 1.1**i, so every daily simple return is exactly 0.10.
_GEO = _bars([100.0 * (1.1**i) for i in range(8)])


def test_momentum_12_1_value_and_warmup() -> None:
    mom = momentum_12_1(_GEO, lookback=4, skip=1)
    # First valid at index 4 (needs close[t-4]); earlier are NaN.
    assert mom.iloc[:4].isna().all()
    # mom[4] = close[3]/close[0] - 1 = 1.1**3 - 1.
    assert mom.iloc[4] == pytest.approx(1.1**3 - 1.0)


def test_short_term_reversal_is_negated_return() -> None:
    rev = short_term_reversal(_GEO, window=2)
    # rev[2] = -(close[2]/close[0] - 1) = -(1.1**2 - 1).
    assert rev.iloc[2] == pytest.approx(-(1.1**2 - 1.0))


def test_low_volatility_sign_and_zero_vol() -> None:
    # Constant daily return → zero rolling std → low_vol == 0 (and never positive).
    low_vol_geo = low_volatility(_GEO, window=3)
    assert low_vol_geo.iloc[3] == pytest.approx(0.0, abs=1e-12)
    # A varying path has positive vol → low_volatility strictly negative.
    zig = _bars([100, 102, 101, 104, 103, 106, 105, 108])
    low_vol_zig = low_volatility(zig, window=3)
    assert low_vol_zig.dropna().iloc[-1] < 0.0


def test_amihud_illiquidity_matches_definition() -> None:
    bars = _bars([100.0, 110.0, 121.0], volumes=[1000.0, 1000.0, 1000.0])
    amihud = amihud_illiquidity(bars, window=2)
    # daily = |ret| / (close*vol): index1 = 0.1/(110*1000), index2 = 0.1/(121*1000).
    d1 = 0.1 / (110.0 * 1000.0)
    d2 = 0.1 / (121.0 * 1000.0)
    assert amihud.iloc[2] == pytest.approx((d1 + d2) / 2.0)
    assert amihud.iloc[:2].isna().all()  # warm-up


def test_residual_momentum_of_market_on_itself_is_zero() -> None:
    # If a symbol's returns ARE the market, the market-model residual is ~0, so residual
    # momentum is ~0 (varying returns so the regression is well-posed).
    zig = _bars([100, 102, 101, 104, 103, 106, 105, 108, 107, 110, 109, 112])
    market = zig["close"].astype("float64").pct_change(fill_method=None)
    res = residual_momentum(zig, market, lookback=4, skip=1, beta_window=3)
    valid = res.dropna()
    assert len(valid) > 0
    assert valid.abs().max() == pytest.approx(0.0, abs=1e-9)
