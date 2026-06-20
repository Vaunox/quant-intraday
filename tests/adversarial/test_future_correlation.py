"""No-suspicious-future-correlation: no feature may be near-perfectly tied to a future label.

A legitimate feature (computed from data at or before the bar) cannot be ~perfectly
correlated with a forward return; one that mechanically contains the future is. The
threshold is high — this flags egregious leakage, not edge (Deep Dive #1 §2.4(b)).
"""

import pandas as pd
import pytest

from quant.data.features import (
    atr,
    bollinger_percent_b,
    log_return,
    macd_histogram,
    parkinson_volatility,
    realized_volatility,
    rsi,
    trend_strength,
    volatility_regime,
    vwap_deviation,
)
from tests.adversarial import leakage, leaky_features, sample_data

pytestmark = pytest.mark.adversarial

# A longer fixture so the correlations are stable.
_BARS = sample_data.make_bars(200, seed=7)
_LABEL = sample_data.forward_return(_BARS)
_MAX_ABS_CORR = 0.99

_FEATURES: dict[str, leakage.FeatureFn] = {
    "log_return": lambda b: log_return(b, 1),
    "realized_volatility": lambda b: realized_volatility(b, 10),
    "atr": lambda b: atr(b, 10),
    "parkinson_volatility": lambda b: parkinson_volatility(b, 10),
    "vwap_deviation": vwap_deviation,
    "rsi": lambda b: rsi(b, 14),
    "macd_histogram": lambda b: macd_histogram(b, fast=12, slow=26, signal=9),
    "bollinger_percent_b": lambda b: bollinger_percent_b(b, period=20, num_std=2.0),
    "volatility_regime": lambda b: volatility_regime(b, vol_window=10, lookback=30),
    "trend_strength": lambda b: trend_strength(b, window=10),
}


@pytest.mark.parametrize("feature", list(_FEATURES.values()), ids=list(_FEATURES))
def test_real_features_have_no_future_correlation(feature: leakage.FeatureFn) -> None:
    values = feature(_BARS)
    assert isinstance(values, pd.Series)  # these features return a Series
    leakage.assert_no_future_correlation(values, _LABEL, max_abs_corr=_MAX_ABS_CORR)


def test_tripwire_forward_return_feature_is_caught() -> None:
    # A feature that *is* the forward return has |corr| == 1 -> must be flagged.
    leaked = leaky_features.lookahead_return(_BARS)
    with pytest.raises(AssertionError):
        leakage.assert_no_future_correlation(leaked, _LABEL, max_abs_corr=_MAX_ABS_CORR)
