"""Tests for the regime gate (P2.7, Deep Dive #2 §4.1 Step 4).

The Gaussian mixture must **recover well-separated regimes**, be **deterministic** for a fixed
seed, label components **stably** (sorted by the first feature, so no label-switching between
fits), and be **point-in-time** (fit on training rows, applied to unseen rows). The gate then
switches regimes on/off — and :func:`~quant.research.models.regime.select_regime_multipliers`
does so data-drivenly, the operational form of "edge stable across regimes".
"""

import numpy as np
import pandas as pd
import pytest

from quant.research.models.errors import ModelTrainingError
from quant.research.models.regime import (
    GaussianMixtureModel,
    RegimeGate,
    fit_regime_gate,
    regime_returns,
    select_regime_multipliers,
)


def _two_blobs(n: int = 200, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    """Two well-separated 2-D Gaussian blobs; returns the frame and the true blob id per row."""
    rng = np.random.default_rng(seed)
    low = rng.normal(loc=[-3.0, -3.0], scale=0.4, size=(n, 2))
    high = rng.normal(loc=[3.0, 3.0], scale=0.4, size=(n, 2))
    matrix = np.vstack([low, high])
    truth = np.r_[np.zeros(n), np.ones(n)].astype(int)  # low blob = 0, high blob = 1
    frame = pd.DataFrame(matrix, columns=["f0", "f1"])
    return frame, truth


def test_mixture_recovers_well_separated_regimes() -> None:
    frame, truth = _two_blobs()
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    labels = fitted.predict(frame)
    # Components are sorted by first-feature mean, so the low blob is regime 0, high is 1.
    accuracy = (labels == truth).mean()
    assert accuracy > 0.99


def test_components_are_sorted_by_first_feature_mean() -> None:
    frame, _ = _two_blobs()
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    assert fitted.means[0, 0] < fitted.means[1, 0]  # stable, interpretable ordering


def test_fit_is_deterministic_for_a_fixed_seed() -> None:
    frame, _ = _two_blobs()
    first = GaussianMixtureModel(3, random_seed=7).fit(frame)
    second = GaussianMixtureModel(3, random_seed=7).fit(frame)
    assert first.means == pytest.approx(second.means)
    assert first.weights == pytest.approx(second.weights)


def test_responsibilities_sum_to_one() -> None:
    frame, _ = _two_blobs()
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    resp = fitted.predict_proba(frame)
    assert resp.shape == (len(frame), 2)
    assert resp.sum(axis=1) == pytest.approx(np.ones(len(frame)))


def test_regime_assignment_is_point_in_time() -> None:
    # Fit on the training blobs, classify unseen points near each centre — no peeking ahead.
    frame, _ = _two_blobs(seed=0)
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    unseen = pd.DataFrame([[-3.0, -3.0], [3.0, 3.0]], columns=["f0", "f1"])
    assert list(fitted.predict(unseen)) == [0, 1]


def test_mixture_predict_respects_trained_column_order() -> None:
    frame, _ = _two_blobs()
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    reordered = frame[["f1", "f0"]]  # swapped at inference; re-selected by name internally
    assert np.array_equal(fitted.predict(frame), fitted.predict(reordered))


def test_mixture_rejects_bad_construction_and_inputs() -> None:
    with pytest.raises(ModelTrainingError, match="n_components"):
        GaussianMixtureModel(0)
    with pytest.raises(ModelTrainingError, match="max_iter"):
        GaussianMixtureModel(2, max_iter=0)
    with pytest.raises(ModelTrainingError, match="reg_covar"):
        GaussianMixtureModel(2, reg_covar=-1.0)
    frame, _ = _two_blobs(n=1)  # 2 rows total, ask for 3 components
    with pytest.raises(ModelTrainingError, match="rows"):
        GaussianMixtureModel(3).fit(frame)
    with pytest.raises(ModelTrainingError, match="empty"):
        GaussianMixtureModel(2).fit(pd.DataFrame())


# --------------------------------------------------------------------------- #
# RegimeGate
# --------------------------------------------------------------------------- #
def test_gate_scales_signal_by_the_active_regime_multiplier() -> None:
    frame, _ = _two_blobs(n=10)
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    gate = RegimeGate(mixture=fitted, multipliers=(0.0, 1.0))  # regime 0 off, regime 1 on
    signal = np.ones(len(frame))
    gated = gate.gate(signal, frame)
    regimes = gate.regimes(frame)
    assert np.all(gated[regimes == 0] == 0.0)  # switched off
    assert np.all(gated[regimes == 1] == 1.0)  # untouched


def test_gate_rejects_mismatched_multiplier_count() -> None:
    frame, _ = _two_blobs(n=10)
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    with pytest.raises(ModelTrainingError, match="multipliers"):
        RegimeGate(mixture=fitted, multipliers=(1.0,))


def test_gate_rejects_negative_multiplier() -> None:
    frame, _ = _two_blobs(n=10)
    fitted = GaussianMixtureModel(2, random_seed=7).fit(frame)
    with pytest.raises(ModelTrainingError, match="non-negative"):
        RegimeGate(mixture=fitted, multipliers=(-0.5, 1.0))


def test_gate_rejects_misaligned_signal() -> None:
    frame, _ = _two_blobs(n=10)
    gate = RegimeGate(GaussianMixtureModel(2, random_seed=7).fit(frame), (1.0, 1.0))
    with pytest.raises(ModelTrainingError, match="align"):
        gate.gate(np.ones(3), frame)


# --------------------------------------------------------------------------- #
# Data-driven regime selection
# --------------------------------------------------------------------------- #
def test_select_multipliers_switches_off_the_losing_regime() -> None:
    regimes = np.array([0, 0, 0, 1, 1, 1])
    returns = np.array([0.02, 0.03, 0.01, -0.02, -0.01, -0.03])  # regime 0 wins, 1 loses
    assert select_regime_multipliers(regimes, returns, 2) == (1.0, 0.0)


def test_select_multipliers_switches_off_a_too_thin_regime() -> None:
    regimes = np.array([0, 0, 0, 1])
    returns = np.array([0.02, 0.03, 0.01, 0.10])  # regime 1 profitable but a single observation
    assert select_regime_multipliers(regimes, returns, 2, min_observations=2) == (1.0, 0.0)


def test_select_multipliers_marks_an_empty_regime_off() -> None:
    regimes = np.array([0, 0, 0])
    returns = np.array([0.02, 0.03, 0.01])  # regime 1 never occurs
    assert select_regime_multipliers(regimes, returns, 2) == (1.0, 0.0)


def test_select_multipliers_rejects_misalignment() -> None:
    with pytest.raises(ModelTrainingError, match="align"):
        select_regime_multipliers(np.array([0, 1]), np.array([0.1]), 2)


def test_regime_returns_reports_per_regime_mean_and_nan_for_empty() -> None:
    summary = regime_returns(np.array([0, 0, 1]), np.array([0.1, 0.3, -0.2]), 3)
    assert summary[0] == pytest.approx(0.2)
    assert summary[1] == pytest.approx(-0.2)
    assert np.isnan(summary[2])  # regime 2 unobserved


# --------------------------------------------------------------------------- #
# fit_regime_gate convenience
# --------------------------------------------------------------------------- #
def test_fit_regime_gate_with_explicit_multipliers() -> None:
    frame, _ = _two_blobs(n=20)
    gate = fit_regime_gate(frame, 2, multipliers=(0.5, 1.0))
    assert gate.multipliers == (0.5, 1.0)


def test_fit_regime_gate_data_driven_from_returns() -> None:
    frame, truth = _two_blobs(n=50)
    # Regime 0 (low blob) profitable, regime 1 (high blob) unprofitable.
    returns = np.where(truth == 0, 0.02, -0.02)
    gate = fit_regime_gate(frame, 2, returns=returns)
    assert gate.multipliers == (1.0, 0.0)


def test_fit_regime_gate_defaults_to_all_on() -> None:
    frame, _ = _two_blobs(n=20)
    gate = fit_regime_gate(frame, 2)
    assert gate.multipliers == (1.0, 1.0)


def test_fit_regime_gate_rejects_both_multipliers_and_returns() -> None:
    frame, _ = _two_blobs(n=20)
    with pytest.raises(ModelTrainingError, match="not both"):
        fit_regime_gate(frame, 2, multipliers=(1.0, 1.0), returns=np.zeros(40))
