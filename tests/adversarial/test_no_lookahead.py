"""Forward-shift invariance: no feature may change a past value when future bars arrive.

Runs the :func:`~tests.adversarial.leakage.assert_no_lookahead` guarantee across every
feature family (P1.6 + P1.7) and proves the tripwire fires on intentionally-leaky features
(Deep Dive #1 §2.4(a); Part I Rule 2).
"""

import pytest

from quant.core.calendar import NSECalendar
from quant.core.config import load_config
from quant.data.features import (
    atr,
    bid_ask_spread,
    bollinger_bands,
    bollinger_percent_b,
    cci,
    compute_feature_frame,
    cross_sectional_rank,
    depth_imbalance,
    directional_index,
    log_return,
    macd_histogram,
    macd_line,
    money_flow_index,
    order_flow_imbalance,
    parkinson_volatility,
    realized_volatility,
    relative_spread,
    rsi,
    sector_neutral_zscore,
    signed_volume,
    sma,
    time_of_day_features,
    trend_strength,
    volatility_regime,
    volume_weighted_ma,
    vwap_deviation,
    williams_r,
)
from tests.adversarial import leakage, leaky_features, sample_data

pytestmark = pytest.mark.adversarial

_CALENDAR = NSECalendar(frozenset())
_CONFIG = load_config(environ={}).features
_BARS = sample_data.make_bars(120)
_DEPTH = sample_data.make_depth_frame(30)
_TRADES = sample_data.make_trades_frame(30)
_PANEL = sample_data.make_panel(20)

# Bar-based features (and frames), each wrapped to a uniform bars -> Series/frame call.
_BAR_FEATURES: dict[str, leakage.FeatureFn] = {
    "log_return": lambda b: log_return(b, 30),
    "realized_volatility": lambda b: realized_volatility(b, 5),
    "atr": lambda b: atr(b, 5),
    "parkinson_volatility": lambda b: parkinson_volatility(b, 5),
    "vwap_deviation": vwap_deviation,
    "rsi": lambda b: rsi(b, 14),
    "macd_histogram": lambda b: macd_histogram(b, fast=12, slow=26, signal=9),
    "bollinger_percent_b": lambda b: bollinger_percent_b(b, period=20, num_std=2.0),
    "bollinger_bands": lambda b: bollinger_bands(b, period=20, num_std=2.0),
    "macd_line": lambda b: macd_line(b, fast=12, slow=26, signal=9),
    "cci": lambda b: cci(b, 14),
    "directional_index": lambda b: directional_index(b, 14),
    "williams_r": lambda b: williams_r(b, 14),
    "money_flow_index": lambda b: money_flow_index(b, 14),
    "sma": lambda b: sma(b, 10),
    "volume_weighted_ma": lambda b: volume_weighted_ma(b, 10),
    "volatility_regime": lambda b: volatility_regime(b, vol_window=5, lookback=10),
    "trend_strength": lambda b: trend_strength(b, window=5),
    "time_of_day_features": lambda b: time_of_day_features(b, _CALENDAR),
    "compute_feature_frame": lambda b: compute_feature_frame(b, _CONFIG),
}

_DEPTH_FEATURES: dict[str, leakage.FeatureFn] = {
    "bid_ask_spread": bid_ask_spread,
    "relative_spread": relative_spread,
    "depth_imbalance": depth_imbalance,
    "order_flow_imbalance": order_flow_imbalance,
}

_PANEL_FEATURES: dict[str, leakage.FeatureFn] = {
    "cross_sectional_rank": cross_sectional_rank,
    "sector_neutral_zscore": lambda p: sector_neutral_zscore(p, sample_data.PANEL_SECTORS),
}


@pytest.mark.parametrize("feature", list(_BAR_FEATURES.values()), ids=list(_BAR_FEATURES))
def test_bar_features_have_no_lookahead(feature: leakage.FeatureFn) -> None:
    leakage.assert_no_lookahead(feature, _BARS, split=80)


@pytest.mark.parametrize("feature", list(_DEPTH_FEATURES.values()), ids=list(_DEPTH_FEATURES))
def test_depth_features_have_no_lookahead(feature: leakage.FeatureFn) -> None:
    leakage.assert_no_lookahead(feature, _DEPTH, split=18)


def test_signed_volume_has_no_lookahead() -> None:
    leakage.assert_no_lookahead(signed_volume, _TRADES, split=18)


@pytest.mark.parametrize("feature", list(_PANEL_FEATURES.values()), ids=list(_PANEL_FEATURES))
def test_cross_sectional_features_have_no_lookahead(feature: leakage.FeatureFn) -> None:
    leakage.assert_no_lookahead(feature, _PANEL, split=12)


# --- tripwires: the check MUST catch a feature that peeks forward --------------


def test_tripwire_lookahead_return_is_caught() -> None:
    with pytest.raises(AssertionError):
        leakage.assert_no_lookahead(leaky_features.lookahead_return, _BARS, split=80)


def test_tripwire_centered_window_is_caught() -> None:
    with pytest.raises(AssertionError):
        leakage.assert_no_lookahead(leaky_features.centered_volatility, _BARS, split=80)
