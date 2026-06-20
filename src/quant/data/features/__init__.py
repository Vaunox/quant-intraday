"""Feature library: pure point-in-time feature functions and the dual-path harness.

Core families (P1.6): price/return transforms (:mod:`returns`), volatility
(:mod:`volatility`), and intraday VWAP deviation (:mod:`vwap`). Every feature is a pure,
causal transform of a bars frame, so the vectorized (backtest) and incremental (live)
paths produce identical output — see :mod:`quant.data.features.harness`. The remaining
families (microstructure, technicals, cross-sectional, regime) arrive in P1.7.
"""

from quant.data.features.errors import FeatureError
from quant.data.features.harness import (
    compute_feature_frame,
    compute_features_asof,
    feature_names,
)
from quant.data.features.returns import log_return
from quant.data.features.volatility import atr, parkinson_volatility, realized_volatility
from quant.data.features.vwap import intraday_vwap, vwap_deviation

__all__ = [
    "FeatureError",
    "atr",
    "compute_feature_frame",
    "compute_features_asof",
    "feature_names",
    "intraday_vwap",
    "log_return",
    "parkinson_volatility",
    "realized_volatility",
    "vwap_deviation",
]
