"""Tests for isotonic probability calibration via PAVA (P2.6).

The headline properties: the fit is **monotone** (never re-orders the model's ranking) and
**reduces the Brier score** on its fit set (the identity map is a feasible monotone fit, so
the optimum cannot be worse) — the guarantee that makes calibrated sizing safe.
"""

import numpy as np
import pytest

from quant.research.models.calibration import fit_isotonic
from quant.research.models.errors import CalibrationError
from quant.research.models.scoring import brier_score


def test_pava_pools_adjacent_violators() -> None:
    # Classic example: labels [1, 0, 1] at ascending scores -> the first two pool to 0.5.
    calibrator = fit_isotonic(np.array([0.0, 1.0, 2.0]), np.array([1.0, 0.0, 1.0]))
    assert list(calibrator.knots_x) == [0.0, 1.0, 2.0]
    assert calibrator.knots_y == pytest.approx([0.5, 0.5, 1.0])


def test_already_monotone_labels_are_recovered_exactly() -> None:
    calibrator = fit_isotonic(np.array([0.1, 0.2, 0.3, 0.4]), np.array([0.0, 0.0, 1.0, 1.0]))
    assert calibrator.knots_y == pytest.approx([0.0, 0.0, 1.0, 1.0])
    # Linear interpolation halfway between the 0 and 1 knots.
    assert calibrator.predict(np.array([0.25]))[0] == pytest.approx(0.5)


def test_predict_is_monotone_and_bounded() -> None:
    rng = np.random.default_rng(1)
    scores = rng.uniform(size=200)
    labels = (rng.uniform(size=200) < scores).astype("float64")
    calibrator = fit_isotonic(scores, labels)
    grid = np.linspace(-0.5, 1.5, 50)  # spans beyond the fitted range
    calibrated = calibrator.predict(grid)
    assert np.all(np.diff(calibrated) >= -1e-12)  # non-decreasing
    assert np.all((calibrated >= 0.0) & (calibrated <= 1.0))


def test_flat_extrapolation_outside_fitted_range() -> None:
    calibrator = fit_isotonic(np.array([0.2, 0.8]), np.array([0.0, 1.0]))
    assert calibrator.predict(np.array([-3.0]))[0] == pytest.approx(calibrator.knots_y[0])
    assert calibrator.predict(np.array([9.0]))[0] == pytest.approx(calibrator.knots_y[-1])


def test_calibration_never_increases_brier_on_fit_set() -> None:
    rng = np.random.default_rng(2)
    scores = rng.uniform(size=300)
    labels = (rng.uniform(size=300) < (0.3 + 0.4 * scores)).astype("float64")  # miscalibrated
    calibrator = fit_isotonic(scores, labels)
    assert brier_score(labels, calibrator.predict(scores)) <= brier_score(labels, scores) + 1e-12


def test_weights_change_the_fit() -> None:
    scores = np.array([0.0, 0.0, 1.0])
    labels = np.array([1.0, 0.0, 1.0])
    high_first = fit_isotonic(scores, labels, np.array([3.0, 1.0, 1.0])).predict(np.array([0.0]))[0]
    low_first = fit_isotonic(scores, labels, np.array([1.0, 3.0, 1.0])).predict(np.array([0.0]))[0]
    assert high_first == pytest.approx(0.75)  # weighted mean of {1,0} with weights {3,1}
    assert low_first == pytest.approx(0.25)


def test_rejects_malformed_inputs() -> None:
    with pytest.raises(CalibrationError, match="length mismatch"):
        fit_isotonic(np.array([0.1, 0.2]), np.array([1.0]))
    with pytest.raises(CalibrationError, match="at least 2"):
        fit_isotonic(np.array([0.5]), np.array([1.0]))
    with pytest.raises(CalibrationError, match="binary"):
        fit_isotonic(np.array([0.1, 0.2]), np.array([2.0, 0.0]))
    with pytest.raises(CalibrationError, match="finite"):
        fit_isotonic(np.array([np.nan, 0.2]), np.array([1.0, 0.0]))
    with pytest.raises(CalibrationError, match="non-negative"):
        fit_isotonic(np.array([0.1, 0.2]), np.array([1.0, 0.0]), np.array([-1.0, 1.0]))
