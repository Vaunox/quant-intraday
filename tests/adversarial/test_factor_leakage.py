"""P1.8 leakage coverage for the Phase-3X price factors (forward-shift invariance + no future corr).

Every factor must be causal: computing it on a prefix equals the prefix of the full computation
(no lookahead), and it must not be near-perfectly correlated with a *future* return. Scaled-down
windows are used so the factors warm up within the synthetic panel — the invariance the suite
proves is window-size-independent.
"""

import pandas as pd
import pytest

from quant.research.factors import (
    amihud_illiquidity,
    low_volatility,
    momentum_12_1,
    residual_momentum,
    short_term_reversal,
)
from tests.adversarial import leakage, sample_data

pytestmark = pytest.mark.adversarial

_BARS = sample_data.make_bars(180, seed=7)
_LABEL = sample_data.forward_return(_BARS)
_MAX_ABS_CORR = 0.99


def _market(bars: pd.DataFrame) -> pd.Series:
    """A market-return proxy derived from the same bars (prefix-consistent for the leakage test)."""
    return bars["close"].astype("float64").pct_change(fill_method=None)


_FACTORS: dict[str, leakage.FeatureFn] = {
    "momentum_12_1": lambda b: momentum_12_1(b, lookback=40, skip=5),
    "short_term_reversal": lambda b: short_term_reversal(b, window=10),
    "low_volatility": lambda b: low_volatility(b, window=20),
    "amihud_illiquidity": lambda b: amihud_illiquidity(b, window=20),
    "residual_momentum": lambda b: residual_momentum(
        b, _market(b), lookback=40, skip=5, beta_window=20
    ),
}


@pytest.mark.parametrize("factor", list(_FACTORS.values()), ids=list(_FACTORS))
def test_factor_has_no_lookahead(factor: leakage.FeatureFn) -> None:
    leakage.assert_no_lookahead(factor, _BARS, split=140)


@pytest.mark.parametrize("factor", list(_FACTORS.values()), ids=list(_FACTORS))
def test_factor_has_no_future_correlation(factor: leakage.FeatureFn) -> None:
    values = factor(_BARS)
    assert isinstance(values, pd.Series)
    leakage.assert_no_future_correlation(values, _LABEL, max_abs_corr=_MAX_ABS_CORR)
