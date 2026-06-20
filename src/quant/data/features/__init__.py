"""Feature library: pure point-in-time feature functions and the dual-path harness.

Families:

* Core (P1.6): price/return transforms (:mod:`returns`), volatility (:mod:`volatility`),
  intraday VWAP deviation (:mod:`vwap`) — assembled by the dual-path :mod:`harness`.
* Extended (P1.7): microstructure / order-flow (:mod:`microstructure`), TA-Lib technicals
  (:mod:`technical`), cyclical time-of-day (:mod:`temporal`), cross-sectional sector-neutral
  ranks (:mod:`cross_sectional`), and regime descriptors (:mod:`regime`).
* Normalization (:mod:`normalize`): trailing rolling / robust scaling + winsorization (§2.3).

Every feature is a pure, causal transform of its inputs (bars, depth book, trade tape, or
a cross-sectional panel), so it is point-in-time correct by construction.
"""

from quant.data.features.cross_sectional import cross_sectional_rank, sector_neutral_zscore
from quant.data.features.errors import FeatureError
from quant.data.features.harness import (
    compute_feature_frame,
    compute_features_asof,
    feature_names,
)
from quant.data.features.microstructure import (
    bid_ask_spread,
    depth_imbalance,
    depth_to_frame,
    order_flow_imbalance,
    relative_spread,
    signed_volume,
    trades_to_frame,
)
from quant.data.features.normalize import robust_zscore, rolling_zscore, winsorize
from quant.data.features.regime import trend_strength, volatility_regime
from quant.data.features.returns import log_return
from quant.data.features.technical import bollinger_percent_b, macd_histogram, rsi
from quant.data.features.temporal import time_of_day_features
from quant.data.features.volatility import atr, parkinson_volatility, realized_volatility
from quant.data.features.vwap import intraday_vwap, vwap_deviation

__all__ = [
    "FeatureError",
    "atr",
    "bid_ask_spread",
    "bollinger_percent_b",
    "compute_feature_frame",
    "compute_features_asof",
    "cross_sectional_rank",
    "depth_imbalance",
    "depth_to_frame",
    "feature_names",
    "intraday_vwap",
    "log_return",
    "macd_histogram",
    "order_flow_imbalance",
    "parkinson_volatility",
    "realized_volatility",
    "relative_spread",
    "robust_zscore",
    "rolling_zscore",
    "rsi",
    "sector_neutral_zscore",
    "signed_volume",
    "time_of_day_features",
    "trades_to_frame",
    "trend_strength",
    "volatility_regime",
    "vwap_deviation",
    "winsorize",
]
