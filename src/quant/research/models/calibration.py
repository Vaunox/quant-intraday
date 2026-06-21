"""Isotonic probability calibration (Deep Dive #2 §4.2 — "calibration is mandatory").

*"Raw boosting probabilities are not calibrated; apply isotonic/Platt scaling on a held-out
(purged) set."* If you size by conviction (fractional Kelly off the meta-probability, Deep
Dive #3), an uncalibrated probability makes the sizing *"garbage"* (§3.4). This module fits
the **isotonic** form: the monotone non-decreasing step function that best maps a model's
raw score to an empirical probability, via the Pool-Adjacent-Violators Algorithm (PAVA).

It is hand-rolled — a clean, exact ~30-line algorithm — rather than importing scikit-learn,
keeping the model stack's only third-party dependency LightGBM (the same lean call as P2.2's
stdlib ``NormalDist`` over SciPy). The fit is **monotone by construction**, so it never
re-orders the model's ranking; it only re-levels the probabilities. The held-out, leak-free
calibration set is the natural by-product of purged cross-validation: the pooled
out-of-fold predictions (:mod:`~quant.research.models.baseline`), each made by a model that
never saw — and was purged around — its own observation.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.models.errors import CalibrationError


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    """A fitted monotone score→probability map, stored as interpolation knots.

    ``knots_x`` are the (unique, ascending) raw scores and ``knots_y`` the calibrated
    probabilities the PAVA fit assigns to them. :meth:`predict` linearly interpolates
    between knots and holds the end values flat outside the fitted range.
    """

    knots_x: npt.NDArray[np.float64]
    knots_y: npt.NDArray[np.float64]

    def predict(self, scores: npt.NDArray[np.float64] | pd.Series) -> npt.NDArray[np.float64]:
        """Map raw ``scores`` to calibrated probabilities in ``[0, 1]``.

        Linear interpolation between knots; flat extrapolation (the nearest knot's value)
        outside the fitted score range, so the output can never leave ``[0, 1]``.
        """
        raw = np.asarray(scores, dtype="float64").ravel()
        calibrated: npt.NDArray[np.float64] = np.interp(raw, self.knots_x, self.knots_y)
        return np.clip(calibrated, 0.0, 1.0)


def fit_isotonic(
    scores: npt.NDArray[np.float64] | pd.Series,
    labels: npt.NDArray[np.float64] | pd.Series,
    weights: npt.NDArray[np.float64] | pd.Series | None = None,
) -> IsotonicCalibrator:
    """Fit an :class:`IsotonicCalibrator` mapping ``scores`` to empirical ``labels``.

    Args:
        scores: Raw model scores/probabilities (the calibration set's predictions).
        labels: Binary outcomes ``{0, 1}`` aligned to ``scores``.
        weights: Optional per-point weights (e.g. average-uniqueness sample weights, P2.4);
            uniform if omitted.

    Returns:
        The fitted calibrator (monotone non-decreasing).

    Raises:
        CalibrationError: If lengths mismatch, fewer than two points are given, labels are
            not binary, or any input is non-finite.
    """
    raw = np.asarray(scores, dtype="float64").ravel()
    truth = np.asarray(labels, dtype="float64").ravel()
    weight = np.ones_like(raw) if weights is None else np.asarray(weights, dtype="float64").ravel()
    _validate_fit_inputs(raw, truth, weight)

    # Aggregate identical scores into one weighted point first, so the fit is a clean
    # function of the score (unique, ascending knots) before PAVA enforces monotonicity.
    order = np.argsort(raw, kind="mergesort")
    unique_x, mean_y, summed_w = _aggregate_by_score(raw[order], truth[order], weight[order])
    fitted_y = _pava(mean_y, summed_w)
    return IsotonicCalibrator(knots_x=unique_x, knots_y=np.clip(fitted_y, 0.0, 1.0))


def _validate_fit_inputs(
    raw: npt.NDArray[np.float64],
    truth: npt.NDArray[np.float64],
    weight: npt.NDArray[np.float64],
) -> None:
    """Fail loud on any malformed calibration input (Ground Rule 7)."""
    if not (raw.shape[0] == truth.shape[0] == weight.shape[0]):
        raise CalibrationError(
            f"scores/labels/weights length mismatch: "
            f"{raw.shape[0]}/{truth.shape[0]}/{weight.shape[0]}"
        )
    if raw.shape[0] < 2:
        raise CalibrationError(f"need at least 2 points to calibrate, got {raw.shape[0]}")
    if not (np.all(np.isfinite(raw)) and np.all(np.isfinite(weight))):
        raise CalibrationError("scores and weights must be finite")
    if not np.all((truth == 0.0) | (truth == 1.0)):
        raise CalibrationError("labels must be binary {0, 1}")
    if np.any(weight < 0.0):
        raise CalibrationError("weights must be non-negative")


def _aggregate_by_score(
    sorted_x: npt.NDArray[np.float64],
    sorted_y: npt.NDArray[np.float64],
    sorted_w: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Collapse points with identical score into one weighted-mean point (ascending unique x)."""
    unique_x, inverse = np.unique(sorted_x, return_inverse=True)
    inverse = inverse.ravel()
    summed_w = np.zeros(unique_x.shape[0], dtype="float64")
    weighted_y = np.zeros(unique_x.shape[0], dtype="float64")
    np.add.at(summed_w, inverse, sorted_w)
    np.add.at(weighted_y, inverse, sorted_w * sorted_y)
    # A group of zero total weight contributes nothing; guard the division.
    safe_w = np.where(summed_w > 0.0, summed_w, 1.0)
    mean_y = weighted_y / safe_w
    return unique_x, mean_y, summed_w


def _pava(
    values: npt.NDArray[np.float64], weights: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Weighted Pool-Adjacent-Violators: the best non-decreasing fit to ``values``.

    Sweeps left to right maintaining a stack of pooled blocks ``(mean, weight, count)``;
    whenever a new point's block would sit below its left neighbour (a monotonicity
    violation) the two are pooled into their weighted mean, cascading left until the stack
    is again non-decreasing. Expanding the blocks back out gives the fitted value per input.
    """
    block_mean: list[float] = []
    block_weight: list[float] = []
    block_count: list[int] = []
    for value, weight in zip(values.tolist(), weights.tolist(), strict=True):
        mean, total, count = value, weight, 1
        # Pool with each left block that violates (its mean >= the running mean).
        while block_mean and block_mean[-1] >= mean:
            prev_mean = block_mean.pop()
            prev_weight = block_weight.pop()
            prev_count = block_count.pop()
            total = prev_weight + weight
            mean = (prev_mean * prev_weight + mean * weight) / total if total > 0 else prev_mean
            weight = total
            count += prev_count
        block_mean.append(mean)
        block_weight.append(weight)
        block_count.append(count)

    fitted = np.empty(values.shape[0], dtype="float64")
    position = 0
    for mean, count in zip(block_mean, block_count, strict=True):
        fitted[position : position + count] = mean
        position += count
    return fitted
