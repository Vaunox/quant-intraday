"""Tests for the dual-path feature harness (P1.6).

The headline is the **skew test**: the incremental (live) feature vector at every bar
equals the corresponding row of the vectorized (backtest) frame — the train/serve skew
tripwire (Deep Dive #1 §2.4). Also covers point-in-time invariance, purity, schema, and
the feature_names ↔ columns lock.
"""

from datetime import date, datetime

import pandas as pd
import pytest

from quant.core.config import FeaturesConfig, load_config
from quant.data.features.errors import FeatureError
from quant.data.features.harness import (
    compute_feature_frame,
    compute_features_asof,
    feature_names,
)
from quant.data.store.errors import SchemaError
from tests.unit.hygiene_fakes import IST, at, frame, good

# A small feature set so a compact fixture still exercises every family.
TEST_CFG = load_config(environ={}).features.model_copy(
    update={
        "return_horizons": (1, 2, 3),
        "volatility_window": 3,
        "atr_window": 3,
        "parkinson_window": 3,
        "feature_set_version": "test",
    }
)


def _bars() -> pd.DataFrame:
    """16 varied bars across two IST sessions (so the VWAP reset is exercised too)."""
    bars = []
    for day in (date(2024, 6, 3), date(2024, 6, 4)):
        for minute in range(8):
            close = 100.0 + ((day.day * 3 + minute * 2) % 7) * 0.5
            bars.append(good("RELIANCE", at(day, 9, 15 + minute), close, vol=100 + minute))
    return frame(bars)


def test_vectorized_equals_incremental_bar_by_bar() -> None:
    """THE skew tripwire: live(asof) == backtest.loc[asof] for every bar."""
    bars = _bars()
    vectorized = compute_feature_frame(bars, TEST_CFG)
    for timestamp in bars["timestamp"]:
        incremental = compute_features_asof(bars, timestamp, TEST_CFG)
        pd.testing.assert_series_equal(
            incremental, vectorized.loc[timestamp], check_names=False, rtol=1e-12, atol=1e-12
        )


def test_no_lookahead_prefix_invariance() -> None:
    # Features of a prefix equal the first rows of the full computation: no future bar
    # can change a past feature value (point-in-time correctness, §2.1).
    bars = _bars()
    full = compute_feature_frame(bars, TEST_CFG)
    prefix = compute_feature_frame(bars.iloc[:10], TEST_CFG)
    pd.testing.assert_frame_equal(prefix, full.iloc[:10], check_exact=False)


def test_columns_match_feature_names() -> None:
    columns = list(compute_feature_frame(_bars(), TEST_CFG).columns)
    assert columns == feature_names(TEST_CFG)


def test_index_is_bar_timestamps() -> None:
    bars = _bars()
    feats = compute_feature_frame(bars, TEST_CFG)
    assert list(feats.index) == list(bars["timestamp"])
    assert feats.index.name == "timestamp"


def test_does_not_mutate_input() -> None:
    bars = _bars()
    before = bars.copy(deep=True)
    compute_feature_frame(bars, TEST_CFG)
    pd.testing.assert_frame_equal(bars, before)


def test_deterministic() -> None:
    bars = _bars()
    pd.testing.assert_frame_equal(
        compute_feature_frame(bars, TEST_CFG), compute_feature_frame(bars, TEST_CFG)
    )


def test_empty_bars_yield_empty_frame_with_columns() -> None:
    feats = compute_feature_frame(frame([]), TEST_CFG)
    assert feats.empty
    assert list(feats.columns) == feature_names(TEST_CFG)


def test_compute_features_asof_returns_named_vector() -> None:
    bars = _bars()
    last = bars["timestamp"].iloc[-1]
    vector = compute_features_asof(bars, last, TEST_CFG)
    assert list(vector.index) == feature_names(TEST_CFG)


def test_compute_features_asof_before_history_raises() -> None:
    with pytest.raises(FeatureError, match="no bars"):
        compute_features_asof(_bars(), datetime(2020, 1, 1, tzinfo=IST), TEST_CFG)


def test_bad_schema_rejected() -> None:
    with pytest.raises(SchemaError):
        compute_feature_frame(_bars().drop(columns=["volume"]), TEST_CFG)


def test_default_config_feature_set() -> None:
    cfg: FeaturesConfig = load_config(environ={}).features
    assert feature_names(cfg) == [
        "ret_1",
        "ret_3",
        "ret_5",
        "ret_15",
        "ret_30",
        "ret_60",
        "rvol_15",
        "atr_14",
        "parkinson_15",
        "vwap_dev",
    ]
