"""Tests for the Sharpe statistics — PSR / DSR (P2.2, Deep Dive #2 §4b.3).

The corrections are checked against an independent assembly of their reference formulas
(via the stdlib :class:`statistics.NormalDist`), plus the qualitative property that runs.
"""

import math
from statistics import NormalDist

import numpy as np
import pytest

from quant.research.validation.errors import MetricError
from quant.research.validation.metrics import (
    deflated_sharpe_ratio,
    deflated_sharpe_ratio_from_returns,
    expected_maximum_sharpe_ratio,
    probabilistic_sharpe_ratio,
    return_moments,
    sharpe_ratio,
)

GAMMA = 0.5772156649015329
NORMAL = NormalDist()


# --- sharpe ratio ------------------------------------------------------------


def test_sharpe_is_mean_over_sample_std() -> None:
    # mean=2, sample std (ddof=1) of [1,2,3] = 1 -> SR = 2.
    assert sharpe_ratio([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_sharpe_annualises_by_sqrt_periods() -> None:
    assert sharpe_ratio([1.0, 2.0, 3.0], periods_per_year=4) == pytest.approx(2.0 * 2.0)


def test_sharpe_drops_nans() -> None:
    assert sharpe_ratio([np.nan, 1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_flat_stream_has_zero_sharpe() -> None:
    assert sharpe_ratio([0.0, 0.0, 0.0]) == 0.0


def test_sharpe_needs_two_observations() -> None:
    with pytest.raises(MetricError, match="2 finite returns"):
        sharpe_ratio([0.01])


def test_riskless_nonzero_stream_is_undefined() -> None:
    with pytest.raises(MetricError, match="zero dispersion"):
        sharpe_ratio([0.02, 0.02, 0.02])


# --- moments -----------------------------------------------------------------


def test_return_moments_match_independent_computation() -> None:
    returns = np.array([0.01, -0.02, 0.03, 0.00, 0.015, -0.005])
    sharpe, skew, kurt, n = return_moments(returns)
    mean = returns.mean()
    m2 = ((returns - mean) ** 2).mean()
    m3 = ((returns - mean) ** 3).mean()
    m4 = ((returns - mean) ** 4).mean()
    assert n == 6
    assert sharpe == pytest.approx(mean / returns.std(ddof=1))
    assert skew == pytest.approx(m3 / m2**1.5)
    assert kurt == pytest.approx(m4 / m2**2)  # non-excess (normal -> 3)


def test_return_moments_need_two_observations() -> None:
    with pytest.raises(MetricError, match="2 finite returns"):
        return_moments([0.01])


def test_return_moments_reject_zero_dispersion() -> None:
    with pytest.raises(MetricError, match="zero dispersion"):
        return_moments([0.02, 0.02, 0.02])


# --- probabilistic Sharpe ratio ----------------------------------------------


def test_psr_matches_reference_formula() -> None:
    sr, n_obs, skew, kurt, benchmark = 0.15, 250, -0.3, 4.0, 0.0
    variance_term = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    expected = NORMAL.cdf((sr - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(variance_term))
    assert probabilistic_sharpe_ratio(sr, n_obs, skew, kurt, benchmark) == pytest.approx(expected)


def test_psr_reduces_to_normal_cdf_for_mesokurtic_symmetric() -> None:
    # skew=0, kurt=1 makes the variance term exactly 1 -> PSR = Phi(SR*sqrt(T-1)).
    sr, n_obs = 0.1, 101
    assert probabilistic_sharpe_ratio(sr, n_obs, 0.0, 1.0, 0.0) == pytest.approx(
        NORMAL.cdf(sr * math.sqrt(n_obs - 1))
    )


def test_psr_is_lower_against_a_higher_benchmark() -> None:
    base = probabilistic_sharpe_ratio(0.2, 500, 0.0, 3.0, 0.0)
    harder = probabilistic_sharpe_ratio(0.2, 500, 0.0, 3.0, 0.1)
    assert harder < base


def test_psr_rejects_too_few_observations() -> None:
    with pytest.raises(MetricError, match="2 observations"):
        probabilistic_sharpe_ratio(0.2, 1, 0.0, 3.0)


def test_psr_rejects_non_positive_variance_term() -> None:
    # 1 - skew*SR + (kurt-1)/4*SR^2 = 1 - 2*2 + 0 = -3.
    with pytest.raises(MetricError, match="variance term"):
        probabilistic_sharpe_ratio(2.0, 100, 2.0, 1.0)


# --- expected maximum Sharpe (DSR benchmark) ---------------------------------


def test_expected_maximum_sharpe_matches_formula() -> None:
    variance, n_trials = 0.04, 25
    z1 = NORMAL.inv_cdf(1 - 1 / n_trials)
    z2 = NORMAL.inv_cdf(1 - 1 / (n_trials * math.e))
    expected = math.sqrt(variance) * ((1 - GAMMA) * z1 + GAMMA * z2)
    assert expected_maximum_sharpe_ratio(variance, n_trials) == pytest.approx(expected)


def test_single_trial_has_zero_benchmark() -> None:
    assert expected_maximum_sharpe_ratio(0.04, 1) == 0.0


def test_more_trials_raise_the_benchmark() -> None:
    assert expected_maximum_sharpe_ratio(0.04, 100) > expected_maximum_sharpe_ratio(0.04, 10)


def test_expected_maximum_rejects_bad_inputs() -> None:
    with pytest.raises(MetricError, match="non-negative"):
        expected_maximum_sharpe_ratio(-0.01, 10)
    with pytest.raises(MetricError, match="n_trials"):
        expected_maximum_sharpe_ratio(0.01, 0)


# --- deflated Sharpe ratio ---------------------------------------------------


def test_dsr_is_psr_at_the_expected_maximum_benchmark() -> None:
    sr, n_obs, skew, kurt, variance, n_trials = 0.2, 500, 0.1, 3.5, 0.02, 20
    benchmark = expected_maximum_sharpe_ratio(variance, n_trials)
    assert deflated_sharpe_ratio(sr, n_obs, skew, kurt, variance, n_trials) == pytest.approx(
        probabilistic_sharpe_ratio(sr, n_obs, skew, kurt, benchmark)
    )


def test_dsr_single_trial_equals_psr_against_zero() -> None:
    sr, n_obs, skew, kurt = 0.2, 500, 0.0, 3.0
    assert deflated_sharpe_ratio(sr, n_obs, skew, kurt, 0.0, 1) == pytest.approx(
        probabilistic_sharpe_ratio(sr, n_obs, skew, kurt, 0.0)
    )


def test_more_trials_deflate_the_sharpe() -> None:
    args = (0.2, 2000, 0.0, 3.0)
    assert deflated_sharpe_ratio(*args, 0.02, 500) < deflated_sharpe_ratio(*args, 0.02, 5)


def test_dsr_from_returns_matches_explicit_path() -> None:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.001, 0.01, size=750)
    sr, skew, kurt, n_obs = return_moments(returns)
    assert deflated_sharpe_ratio_from_returns(returns, 0.03, 40) == pytest.approx(
        deflated_sharpe_ratio(sr, n_obs, skew, kurt, 0.03, 40)
    )
    assert 0.0 <= deflated_sharpe_ratio_from_returns(returns, 0.03, 40) <= 1.0
