"""Tests for permutation (Mean-Decrease-Accuracy) importance (P2.6).

Uses a *deterministic* predict function that depends only on the ``signal`` column, so the
ground truth is exact: shuffling ``signal`` must drop the score, shuffling ``noise`` must not
move it at all. Importance is also reproducible given a seeded RNG (Ground Rule 7).
"""

import numpy as np
import pandas as pd
import pytest

from quant.research.models.errors import ModelTrainingError
from quant.research.models.importance import permutation_importance
from quant.research.models.scoring import neg_log_loss


def _signal_only(frame: pd.DataFrame) -> np.ndarray:
    """A predictor that uses only ``signal`` — so ``noise`` has exactly zero importance."""
    return 1.0 / (1.0 + np.exp(-3.0 * frame["signal"].to_numpy()))


def _dataset(n: int = 300, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n)
    noise = rng.normal(size=n)
    labels = (rng.uniform(size=n) < 1.0 / (1.0 + np.exp(-3.0 * signal))).astype("float64")
    return pd.DataFrame({"signal": signal, "noise": noise}), labels


def test_relevant_feature_outranks_irrelevant_one() -> None:
    features, labels = _dataset()
    importances = permutation_importance(
        _signal_only, features, labels, n_repeats=5, rng=np.random.default_rng(0)
    )
    assert importances["signal"] > 0.05
    # noise never enters the prediction, so permuting it cannot change the score.
    assert importances["noise"] == pytest.approx(0.0, abs=1e-12)


def test_importance_is_deterministic_for_a_fixed_seed() -> None:
    features, labels = _dataset()
    first = permutation_importance(
        _signal_only, features, labels, n_repeats=4, rng=np.random.default_rng(42)
    )
    second = permutation_importance(
        _signal_only, features, labels, n_repeats=4, rng=np.random.default_rng(42)
    )
    assert first == second


def test_scorer_is_pluggable() -> None:
    # A different higher-is-better scorer (neg log loss) still ranks signal above noise.
    features, labels = _dataset()
    importances = permutation_importance(
        _signal_only,
        features,
        labels,
        n_repeats=3,
        rng=np.random.default_rng(1),
        scorer=neg_log_loss,
    )
    assert importances["signal"] > importances["noise"]


def test_rejects_malformed_inputs() -> None:
    features, labels = _dataset(n=20)
    with pytest.raises(ModelTrainingError, match="n_repeats"):
        permutation_importance(
            _signal_only, features, labels, n_repeats=0, rng=np.random.default_rng()
        )
    with pytest.raises(ModelTrainingError, match="empty"):
        permutation_importance(
            _signal_only, features.iloc[:0], labels[:0], n_repeats=1, rng=np.random.default_rng()
        )
    with pytest.raises(ModelTrainingError, match="align"):
        permutation_importance(
            _signal_only, features, labels[:-1], n_repeats=1, rng=np.random.default_rng()
        )
