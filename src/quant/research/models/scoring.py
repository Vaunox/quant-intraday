"""Binary-classification scores for cross-validation and permutation importance (P2.6).

Small, dependency-free metrics over a binary label vector ``y_true`` ∈ ``{0, 1}`` and a
predicted-probability vector ``y_prob`` ∈ ``[0, 1]``. Following the same lean precedent as
the validation metrics (P2.2 used the stdlib :class:`statistics.NormalDist` rather than
pulling in SciPy), these are hand-rolled rather than importing scikit-learn — the model
stack's only third-party dependency is LightGBM itself.

A :data:`Scorer` is a ``(y_true, y_prob) -> float`` callable under the **higher-is-better**
convention, so the same object drives both hyperparameter selection (:mod:`tuning`) and
permutation importance (:mod:`importance`, where a feature's importance is the *drop* in the
score when it is shuffled). :func:`neg_log_loss`, :func:`accuracy`, and :func:`roc_auc` are
higher-is-better; :func:`log_loss` and :func:`brier_score` are the raw (lower-is-better)
losses for reporting.
"""

from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.models.errors import ScoringError

#: A higher-is-better classification score over ``(y_true, y_prob)``.
Scorer = Callable[[npt.NDArray[np.float64], npt.NDArray[np.float64]], float]

#: Clamp for log-loss so a confident wrong prediction yields a large but finite loss.
_LOG_LOSS_EPS = 1e-15


def _validate(
    y_true: npt.NDArray[np.float64] | pd.Series, y_prob: npt.NDArray[np.float64] | pd.Series
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Coerce, align, and bounds-check a label / probability pair (fail loud at the boundary)."""
    truth = np.asarray(y_true, dtype="float64").ravel()
    prob = np.asarray(y_prob, dtype="float64").ravel()
    if truth.shape[0] != prob.shape[0]:
        raise ScoringError(
            f"y_true and y_prob length mismatch: {truth.shape[0]} vs {prob.shape[0]}"
        )
    if truth.shape[0] == 0:
        raise ScoringError("cannot score an empty vector")
    if not np.all((truth == 0.0) | (truth == 1.0)):
        raise ScoringError("y_true must be binary {0, 1}")
    if not np.all(np.isfinite(prob)):
        raise ScoringError("y_prob contains non-finite values")
    if np.any(prob < 0.0) or np.any(prob > 1.0):
        raise ScoringError("y_prob must lie in [0, 1]")
    return truth, prob


def accuracy(
    y_true: npt.NDArray[np.float64] | pd.Series,
    y_prob: npt.NDArray[np.float64] | pd.Series,
    threshold: float = 0.5,
) -> float:
    """Return the fraction of predictions correct at ``threshold`` (Mean-Decrease-*Accuracy*).

    The deep dive names MDA (permutation accuracy drop) the canonical importance score, so
    this is the default scorer there. Higher is better.
    """
    truth, prob = _validate(y_true, y_prob)
    predicted = (prob >= threshold).astype("float64")
    return float((predicted == truth).mean())


def log_loss(
    y_true: npt.NDArray[np.float64] | pd.Series,
    y_prob: npt.NDArray[np.float64] | pd.Series,
) -> float:
    """Return the binary cross-entropy (log loss); **lower is better**.

    Probabilities are clipped to ``[eps, 1-eps]`` so a confidently-wrong prediction incurs a
    large but finite penalty rather than ``inf`` — the natural quality measure for the
    *calibrated* probabilities this layer produces for sizing.
    """
    truth, prob = _validate(y_true, y_prob)
    clipped = np.clip(prob, _LOG_LOSS_EPS, 1.0 - _LOG_LOSS_EPS)
    losses = -(truth * np.log(clipped) + (1.0 - truth) * np.log(1.0 - clipped))
    return float(losses.mean())


def neg_log_loss(
    y_true: npt.NDArray[np.float64] | pd.Series,
    y_prob: npt.NDArray[np.float64] | pd.Series,
) -> float:
    """Return ``-log_loss`` — the higher-is-better :data:`Scorer` form of the log loss."""
    return -log_loss(y_true, y_prob)


def brier_score(
    y_true: npt.NDArray[np.float64] | pd.Series,
    y_prob: npt.NDArray[np.float64] | pd.Series,
) -> float:
    """Return the Brier score (mean squared error of the probability); **lower is better**."""
    truth, prob = _validate(y_true, y_prob)
    return float(((prob - truth) ** 2).mean())


def roc_auc(
    y_true: npt.NDArray[np.float64] | pd.Series,
    y_prob: npt.NDArray[np.float64] | pd.Series,
) -> float:
    """Return the area under the ROC curve via the rank (Mann-Whitney U) identity.

    ``AUC = (sum(ranks of positives) - n_pos*(n_pos+1)/2) / (n_pos * n_neg)`` with average
    ranks for ties — the threshold-free ranking score, robust for the scorer. Higher is better.

    Raises:
        ScoringError: If the labels are a single class (AUC is undefined).
    """
    truth, prob = _validate(y_true, y_prob)
    n_pos = int(truth.sum())
    n_neg = truth.shape[0] - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ScoringError("ROC AUC is undefined for a single-class label vector")
    ranks = _average_ranks(prob)
    rank_sum_pos = float(ranks[truth == 1.0].sum())
    return float((rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def _average_ranks(values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Return 1-based ranks of ``values`` with tied values sharing their average rank."""
    n = values.shape[0]
    order = np.argsort(values, kind="mergesort")  # stable, so ties keep input order
    sorted_values = values[order]
    positions = np.arange(1, n + 1, dtype="float64")
    ranks = np.empty(n, dtype="float64")
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i : j + 1]] = positions[i : j + 1].mean()  # average rank over the tie block
        i = j + 1
    return ranks
