"""Tests for evaluating the ensemble + regime gate under CPCV (P2.7 acceptance criterion).

This is the headline criterion — *"ensemble + regime gate evaluated under CPCV"*. The evaluator
must reconstruct the right number of paths (φ = C(N-1, k-1)), turn a learnable signal into a
**positive** path-Sharpe distribution out-of-sample, and let the **regime gate** recover the edge
when the signal is profitable in one regime and loss-making in another — all strictly point-in-time
(the test block is purged/embargoed; the gate's regime selection uses train returns only).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.research.models.errors import ModelTrainingError
from quant.research.models.estimators import (
    Estimator,
    LightGBMEstimator,
    LogisticEstimator,
    XGBoostEstimator,
)
from quant.research.models.evaluation import (
    evaluate_ensemble_under_cpcv,
    probability_to_position,
)
from quant.research.validation.cpcv import CombinatorialPurgedCV
from tests.unit.models_fakes import model_config

IST = ZoneInfo("Asia/Kolkata")


def _estimators() -> list[Estimator]:
    cfg = model_config()
    return [
        LightGBMEstimator.from_config(cfg),
        XGBoostEstimator.from_config(cfg),
        LogisticEstimator(),
    ]


def _index(n: int) -> pd.DatetimeIndex:
    base = datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    return pd.DatetimeIndex([base + timedelta(minutes=15 * i) for i in range(n)], name="t")


def _dataset(
    n: int = 600, seed: int = 5
) -> tuple[pd.DataFrame, pd.Series, pd.Series, np.ndarray, np.ndarray]:
    """A predictable dataset plus the raw signal and the per-obj 'regime is bad' mask."""
    rng = np.random.default_rng(seed)
    index = _index(n)
    signal = rng.normal(size=n)
    labels = pd.Series((signal > 0).astype("int64"), index=index)
    features = pd.DataFrame({"signal": signal, "noise": rng.normal(size=n)}, index=index)
    label_times = pd.Series([index[min(i + 2, n - 1)] for i in range(n)], index=index)
    is_bad = rng.uniform(size=n) < 0.5
    return features, labels, label_times, signal, is_bad


def _noisy_directional_returns(labels: pd.Series, *, seed: int = 99) -> pd.Series:
    """A profitable payoff for the up-label, with realistic magnitude dispersion.

    A unit long earns ~+1% when the label is up and ~-1% otherwise, plus Gaussian noise so the
    strategy's per-observation return stream is not a degenerate constant (a real return series
    always has dispersion — a riskless constant stream has no defined Sharpe).
    """
    rng = np.random.default_rng(seed)
    direction = np.where(labels.to_numpy() == 1, 0.01, -0.01)
    return pd.Series(direction + rng.normal(0.0, 0.005, len(labels)), index=labels.index)


def test_probability_to_position_is_symmetric() -> None:
    out = probability_to_position(np.array([0.0, 0.5, 1.0]))
    assert out == pytest.approx([-1.0, 0.0, 1.0])


def test_evaluation_reconstructs_the_right_number_of_paths() -> None:
    features, labels, label_times, _, _ = _dataset()
    fwd = _noisy_directional_returns(labels)
    cpcv = CombinatorialPurgedCV(6, 2, embargo_pct=0.0)
    evaluation = evaluate_ensemble_under_cpcv(
        _estimators(), features, labels, label_times, fwd, cpcv
    )
    assert evaluation.num_paths == 5  # C(6-1, 2-1) = 5
    assert len(evaluation.paths) == 5


@pytest.mark.parametrize("method", ["rank_average", "stack"])
def test_a_real_edge_yields_a_positive_path_distribution(method: str) -> None:
    features, labels, label_times, _, _ = _dataset()
    # The signal is genuinely profitable: a unit long earns ~+1% when the label is up, else ~-1%.
    fwd = _noisy_directional_returns(labels)
    cpcv = CombinatorialPurgedCV(6, 2, embargo_pct=0.0)
    distribution = evaluate_ensemble_under_cpcv(
        _estimators(), features, labels, label_times, fwd, cpcv, method=method
    ).distribution
    assert distribution.median > 0.5  # honest OOS edge survives the CPCV path reconstruction
    assert distribution.fraction_negative == 0.0


def test_regime_gate_recovers_an_edge_lost_in_one_regime() -> None:
    features, labels, label_times, _, is_bad = _dataset()
    index = features.index
    rng = np.random.default_rng(11)
    # The signal pays off in the good regime and loses in the bad one; the regime feature
    # cleanly separates the two so the GMM can recover them.
    profitable = np.where(labels.to_numpy() == 1, 0.01, -0.01)
    fwd = pd.Series(np.where(is_bad, -profitable, profitable), index=index)
    regime_features = pd.DataFrame(
        {"r": np.where(is_bad, 3.0, -3.0) + rng.normal(0, 0.3, len(index))}, index=index
    )
    cpcv = CombinatorialPurgedCV(6, 2, embargo_pct=0.0)

    ungated = evaluate_ensemble_under_cpcv(
        _estimators(), features, labels, label_times, fwd, cpcv
    ).distribution
    gated = evaluate_ensemble_under_cpcv(
        _estimators(),
        features,
        labels,
        label_times,
        fwd,
        cpcv,
        regime_features=regime_features,
        n_regimes=2,
    ).distribution

    assert ungated.median < 0.2  # the two regimes cancel — no net edge ungated
    assert gated.median > 0.3  # switching off the loss-making regime recovers the edge
    assert gated.median > ungated.median


def test_evaluation_rejects_misaligned_labels() -> None:
    features, labels, label_times, _, _ = _dataset(n=200)
    fwd = pd.Series(np.zeros(200), index=features.index)
    cpcv = CombinatorialPurgedCV(5, 2)
    with pytest.raises(ModelTrainingError, match="share one index"):
        evaluate_ensemble_under_cpcv(
            _estimators(), features, labels.reset_index(drop=True), label_times, fwd, cpcv
        )


def test_evaluation_rejects_misaligned_forward_returns() -> None:
    features, labels, label_times, _, _ = _dataset(n=200)
    fwd = pd.Series(np.zeros(200))  # RangeIndex, not the features index
    cpcv = CombinatorialPurgedCV(5, 2)
    with pytest.raises(ModelTrainingError, match="forward_returns"):
        evaluate_ensemble_under_cpcv(_estimators(), features, labels, label_times, fwd, cpcv)


def test_evaluation_rejects_misaligned_regime_features() -> None:
    features, labels, label_times, _, _ = _dataset(n=200)
    fwd = pd.Series(np.zeros(200), index=features.index)
    bad_regime = pd.DataFrame({"r": np.zeros(200)})  # RangeIndex
    cpcv = CombinatorialPurgedCV(5, 2)
    with pytest.raises(ModelTrainingError, match="regime_features"):
        evaluate_ensemble_under_cpcv(
            _estimators(), features, labels, label_times, fwd, cpcv, regime_features=bad_regime
        )


def test_round_trip_cost_lowers_the_path_distribution() -> None:
    # Charging a per-event round-trip cost nets the returns down — the P2.9 "after costs" basis.
    features, labels, label_times, _, _ = _dataset()
    fwd = _noisy_directional_returns(labels)
    cpcv = CombinatorialPurgedCV(6, 2, embargo_pct=0.0)
    gross = evaluate_ensemble_under_cpcv(
        _estimators(), features, labels, label_times, fwd, cpcv
    ).distribution
    net = evaluate_ensemble_under_cpcv(
        _estimators(), features, labels, label_times, fwd, cpcv, round_trip_cost=0.02
    ).distribution
    assert net.median < gross.median  # a 2% round-trip cost eats the ~1% gross edge
