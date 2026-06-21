"""Tests for fractional differentiation + ADF stationarity (P2.5, Deep Dive #2 §3.6)."""

import numpy as np
import pandas as pd
import pytest

from quant.research.features_research.errors import FracDiffError
from quant.research.features_research.frac_diff import (
    adf_test,
    frac_diff,
    frac_diff_weights,
    min_ffd,
)


def _random_walk(n: int, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(rng.standard_normal(n)) * 0.01 + np.log(100), index=pd.RangeIndex(n))


# --- weights -----------------------------------------------------------------


def test_weights_identity_at_zero() -> None:
    assert list(frac_diff_weights(0.0)) == [1.0]


def test_weights_first_difference_at_one() -> None:
    assert list(frac_diff_weights(1.0)) == [1.0, -1.0]


def test_weights_decay_for_fractional_order() -> None:
    weights = frac_diff_weights(0.5)
    assert weights[0] == 1.0
    assert weights[1] == pytest.approx(-0.5)
    assert weights[2] == pytest.approx(-0.125)
    assert np.all(np.abs(np.diff(np.abs(weights))) >= 0) or np.abs(weights[-1]) >= 1e-5


def test_smaller_threshold_widens_the_window() -> None:
    assert len(frac_diff_weights(0.4, 1e-5)) > len(frac_diff_weights(0.4, 1e-3))


@pytest.mark.parametrize("bad_d", [-0.1, -1.0])
def test_negative_order_rejected(bad_d: float) -> None:
    with pytest.raises(FracDiffError, match="non-negative"):
        frac_diff_weights(bad_d)


def test_non_positive_threshold_rejected() -> None:
    with pytest.raises(FracDiffError, match="threshold"):
        frac_diff_weights(0.5, 0.0)


# --- frac_diff ---------------------------------------------------------------


def test_order_one_is_the_first_difference() -> None:
    series = pd.Series([100.0, 101.0, 103.0, 102.0, 105.0])
    result = frac_diff(series, 1.0)
    assert pd.isna(result.iloc[0])  # one-bar warm-up
    assert list(result.iloc[1:]) == [1.0, 2.0, -1.0, 3.0]


def test_order_zero_returns_the_series() -> None:
    series = pd.Series([100.0, 101.0, 103.0])
    assert list(frac_diff(series, 0.0)) == [100.0, 101.0, 103.0]


def test_is_causal_with_window_warmup() -> None:
    series = _random_walk(50)
    width = len(frac_diff_weights(0.5)) - 1
    result = frac_diff(series, 0.5)
    assert result.iloc[:width].isna().all()  # the first `width` bars are NaN
    assert result.iloc[width:].notna().all()


def test_nan_input_rejected() -> None:
    series = pd.Series([100.0, np.nan, 102.0])
    with pytest.raises(FracDiffError, match="NaN"):
        frac_diff(series, 0.5)


# --- ADF ---------------------------------------------------------------------


def test_white_noise_is_stationary() -> None:
    rng = np.random.default_rng(1)
    noise = pd.Series(rng.standard_normal(500))
    assert adf_test(noise).is_stationary()


def test_random_walk_is_not_stationary() -> None:
    assert not adf_test(_random_walk(500)).is_stationary()


def test_adf_result_fields() -> None:
    result = adf_test(_random_walk(300))
    assert "5%" in result.critical_values
    assert result.n_obs > 0
    assert 0.0 <= result.pvalue <= 1.0


def test_adf_too_few_observations_rejected() -> None:
    with pytest.raises(FracDiffError, match="at least"):
        adf_test(pd.Series([1.0, 2.0, 3.0]))


# --- min_ffd: the headline acceptance ----------------------------------------


def test_min_ffd_finds_minimal_stationary_order() -> None:
    walk = _random_walk(2000)
    assert not adf_test(walk).is_stationary()  # raw is non-stationary
    result = min_ffd(walk)
    assert 0.0 < result.d < 1.0  # fractional, between raw and returns
    assert result.adf.is_stationary()  # the differenced series passes ADF


def test_min_ffd_retains_more_memory_than_returns() -> None:
    # The headline §3.6 property: the min-d series stays correlated with the level (memory),
    # where full differencing (returns) does not.
    walk = _random_walk(2000)
    result = min_ffd(walk)
    returns = frac_diff(walk, 1.0)
    mask = result.series.notna() & returns.notna()
    corr_min_d = abs(np.corrcoef(result.series[mask], walk[mask])[0, 1])
    corr_returns = abs(np.corrcoef(returns[mask], walk[mask])[0, 1])
    assert corr_min_d > corr_returns


def test_min_ffd_is_zero_for_already_stationary_series() -> None:
    rng = np.random.default_rng(3)
    noise = pd.Series(rng.standard_normal(1000))
    assert min_ffd(noise).d == 0.0  # raw is already stationary


def test_min_ffd_custom_grid() -> None:
    result = min_ffd(_random_walk(2000), d_candidates=[0.4, 0.6, 0.8, 1.0])
    assert result.d in {0.4, 0.6, 0.8, 1.0}


def test_min_ffd_raises_when_no_candidate_is_stationary() -> None:
    with pytest.raises(FracDiffError, match="stationarity"):
        min_ffd(_random_walk(2000), d_candidates=[0.0])  # raw stays non-stationary
