"""Tests for the cycle-3a finer-grid feature path (Phase 2R; Part II "features from finer data").

Features are computed on a finer bar grid (e.g. 5-min) and point-in-time aligned to the 15-min
decision rows. These pin: the alignment maps each decision bar to the finer bar that closes at the
same instant (no lookahead), the finer path actually changes the features, the legacy path is
exactly preserved (``None`` or ``== decision`` frequency), and a non-dividing frequency fails loud.
"""

import numpy as np
import pandas as pd
import pytest

from quant.core.config import Config
from quant.research.pipeline.dataset import (
    _align_fine_to_decision,
    build_symbol_dataset,
)
from quant.research.pipeline.errors import PipelineError
from tests.unit.pipeline_fakes import minute_bars, pipeline_config


def _config_with_feature_frequency(minutes: int | None) -> Config:
    config = pipeline_config()
    return config.model_copy(
        update={
            "features": config.features.model_copy(update={"feature_frequency_minutes": minutes})
        }
    )


def test_align_fine_to_decision_matches_close_instants() -> None:
    # A 15-min decision bar [t, t+15) closes at t+15; the 5-min bar closing then starts at t+10.
    decision = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-01 09:15", "2024-01-01 09:30"]).tz_localize("Asia/Kolkata"),
        name="timestamp",
    )
    fine = pd.DataFrame(
        {"v": [1.0, 2.0]},
        index=pd.to_datetime(["2024-01-01 09:25", "2024-01-01 09:40"]).tz_localize("Asia/Kolkata"),
    )
    aligned = _align_fine_to_decision(fine, decision, decision=15, fine=5)
    assert list(aligned.index) == list(decision)  # relabelled to the decision rows
    assert aligned["v"].tolist() == [1.0, 2.0]  # decision T takes the finer bar at T+10


def test_align_fine_to_decision_gap_yields_nan() -> None:
    decision = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-01 09:15", "2024-01-01 09:30"]).tz_localize("Asia/Kolkata"),
        name="timestamp",
    )
    fine = pd.DataFrame(
        {"v": [1.0]},  # only the first decision bar's finer bar exists
        index=pd.to_datetime(["2024-01-01 09:25"]).tz_localize("Asia/Kolkata"),
    )
    aligned = _align_fine_to_decision(fine, decision, decision=15, fine=5)
    assert aligned["v"].tolist()[0] == 1.0
    assert np.isnan(aligned["v"].to_numpy()[1])  # missing finer bar -> NaN, never fabricated


def test_finer_features_align_to_decision_rows_and_change_values() -> None:
    bars = minute_bars("AAA", sessions=30, minutes=120, seed=1, drift=0.00005)
    legacy = build_symbol_dataset("AAA", bars, _config_with_feature_frequency(None))
    finer = build_symbol_dataset("AAA", bars, _config_with_feature_frequency(5))

    # Same feature columns + the events are still sampled on the 15-min clock.
    assert tuple(finer.features.columns) == tuple(legacy.features.columns)
    assert finer.regime_features.index.equals(finer.features.index)
    # The finer grid genuinely changes the features (captures sub-15-min structure).
    shared = legacy.features.index.intersection(finer.features.index)
    assert len(shared) > 0
    diff = (legacy.features.loc[shared] - finer.features.loc[shared]).abs().to_numpy()
    assert float(np.nanmax(diff)) > 0.0


def test_feature_frequency_equal_to_decision_is_the_legacy_path() -> None:
    bars = minute_bars("AAA", sessions=20, minutes=120, seed=3, drift=0.00004)
    legacy = build_symbol_dataset("AAA", bars, _config_with_feature_frequency(None))
    # The decision clock is 15-min; setting the feature frequency equal to it is the legacy path.
    equal = build_symbol_dataset("AAA", bars, _config_with_feature_frequency(15))
    assert equal.features.index.equals(legacy.features.index)
    pd.testing.assert_frame_equal(equal.features, legacy.features)


def test_finer_frequency_must_divide_the_decision_frequency() -> None:
    bars = minute_bars("AAA", sessions=10, minutes=120, seed=1)
    # 15 % 7 != 0 -> the close instants would never align; fail loud (Ground Rule 7).
    with pytest.raises(PipelineError, match="evenly divide"):
        build_symbol_dataset("AAA", bars, _config_with_feature_frequency(7))
