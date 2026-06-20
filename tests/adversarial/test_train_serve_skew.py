"""Train/serve skew: the vectorized (backtest) and incremental (live) paths must agree.

Enforces the dual-path equality of the P1.6 harness across every bar and proves the check
catches a feature whose two paths diverge (Deep Dive #1 §2.4).
"""

from datetime import datetime

import pandas as pd
import pytest

from quant.core.config import load_config
from quant.data.features import compute_feature_frame, compute_features_asof
from tests.adversarial import leakage, leaky_features, sample_data

pytestmark = pytest.mark.adversarial

# Small windows so a compact fixture still exercises every core feature.
_CONFIG = load_config(environ={}).features.model_copy(
    update={
        "return_horizons": (1, 2, 3),
        "volatility_window": 3,
        "atr_window": 3,
        "parkinson_window": 3,
    }
)
_BARS = sample_data.make_bars(30)


def test_harness_is_skew_free() -> None:
    leakage.assert_skew_free(
        lambda bars: compute_feature_frame(bars, _CONFIG),
        lambda bars, asof: compute_features_asof(bars, asof, _CONFIG),
        _BARS,
    )


def test_tripwire_full_sample_feature_has_skew() -> None:
    # A full-sample statistic differs between the vectorized path (whole series) and the
    # incremental path (history truncated at asof) -> the skew check must catch it.
    def frame_fn(bars: pd.DataFrame) -> pd.DataFrame:
        values = leaky_features.full_sample_zscore(bars["close"])
        return pd.DataFrame({"z": values.to_numpy()}, index=pd.DatetimeIndex(bars["timestamp"]))

    def asof_fn(bars: pd.DataFrame, asof: datetime) -> pd.Series:
        history = bars[bars["timestamp"] <= asof]
        return pd.Series({"z": leaky_features.full_sample_zscore(history["close"]).iloc[-1]})

    with pytest.raises(AssertionError):
        leakage.assert_skew_free(frame_fn, asof_fn, _BARS)
