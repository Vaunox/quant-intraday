"""Tests for Probability of Backtest Overfitting via CSCV (P2.2, Deep Dive #2 §4b.4)."""

import math

import numpy as np
import pandas as pd
import pytest

from quant.research.validation.errors import PBOError
from quant.research.validation.pbo import probability_of_backtest_overfitting

# --- structure ---------------------------------------------------------------


def test_evaluates_all_cscv_combinations() -> None:
    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((200, 5))
    result = probability_of_backtest_overfitting(matrix, n_partitions=6)
    assert result.n_combinations == math.comb(6, 3)  # C(S, S/2)
    assert 0.0 <= result.pbo <= 1.0
    assert np.all(np.isfinite(result.logits))


def test_accepts_dataframe_input() -> None:
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(rng.standard_normal((120, 4)))
    result = probability_of_backtest_overfitting(frame, n_partitions=4)
    assert 0.0 <= result.pbo <= 1.0


# --- behaviour ---------------------------------------------------------------


def test_dominant_strategy_gives_low_pbo() -> None:
    # Strategy 0 has a real, persistent edge -> it wins IS and stays top OOS -> PBO ~ 0.
    rng = np.random.default_rng(3)
    matrix = rng.normal(0.0, 0.01, size=(400, 8))
    matrix[:, 0] += 0.02  # persistent positive drift on strategy 0
    result = probability_of_backtest_overfitting(matrix, n_partitions=8)
    assert result.pbo == pytest.approx(0.0, abs=0.05)


def test_pure_noise_gives_pbo_near_half() -> None:
    # No edge anywhere: the IS-best is luck and is ~50/50 above the OOS median.
    rng = np.random.default_rng(12)
    matrix = rng.standard_normal((600, 10))
    result = probability_of_backtest_overfitting(matrix, n_partitions=10)
    assert 0.3 <= result.pbo <= 0.7


def test_overfit_selection_gives_high_pbo() -> None:
    # Build strategies whose in-sample strength is engineered to reverse out-of-sample:
    # each strategy spikes on its "own" partition only, so the IS winner (whichever owns
    # an IS partition) is mediocre/worst on the disjoint OOS partitions.
    n_partitions, per = 8, 30
    n_obs = n_partitions * per
    matrix = np.full((n_obs, n_partitions), -0.001)
    for strat in range(n_partitions):
        block = slice(strat * per, (strat + 1) * per)
        matrix[block, strat] = 0.05  # strategy `strat` only shines on partition `strat`
    result = probability_of_backtest_overfitting(matrix, n_partitions=n_partitions)
    assert result.pbo >= 0.6


# --- validation / fail-loud --------------------------------------------------


def test_one_dimensional_input_rejected() -> None:
    with pytest.raises(PBOError, match=r"\(T, N>=2\)"):
        probability_of_backtest_overfitting(np.zeros(100), n_partitions=4)


def test_single_strategy_rejected() -> None:
    with pytest.raises(PBOError, match="N>=2"):
        probability_of_backtest_overfitting(np.zeros((100, 1)), n_partitions=4)


@pytest.mark.parametrize("n_partitions", [3, 5, 0])
def test_odd_or_too_few_partitions_rejected(n_partitions: int) -> None:
    with pytest.raises(PBOError, match="even"):
        probability_of_backtest_overfitting(np.zeros((100, 3)), n_partitions=n_partitions)


def test_too_few_observations_rejected() -> None:
    # n_partitions=8 needs >= 16 observations.
    with pytest.raises(PBOError, match="at least"):
        probability_of_backtest_overfitting(np.zeros((10, 3)), n_partitions=8)
