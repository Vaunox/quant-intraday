"""Tests for the binary-classification scores (P2.6).

Each metric is checked against a hand-computed value, and the higher-is-better convention
(the contract the importance/tuning scorers rely on) is pinned.
"""

import numpy as np
import pytest

from quant.research.models.errors import ScoringError
from quant.research.models.scoring import (
    accuracy,
    brier_score,
    log_loss,
    neg_log_loss,
    roc_auc,
)


def test_accuracy_counts_correct_predictions_at_threshold() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    prob = np.array([0.9, 0.1, 0.4, 0.6])  # preds at 0.5 -> [1, 0, 0, 1]; 2 of 4 correct
    assert accuracy(y, prob) == 0.5


def test_accuracy_perfect_and_inverted() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert accuracy(y, y) == 1.0
    assert accuracy(y, 1.0 - y) == 0.0


def test_brier_score_is_mean_squared_error() -> None:
    y = np.array([1.0, 0.0])
    prob = np.array([0.75, 0.25])
    assert brier_score(y, prob) == pytest.approx(((0.25**2) + (0.25**2)) / 2)


def test_log_loss_matches_formula_and_neg_is_its_negation() -> None:
    y = np.array([1.0, 0.0])
    prob = np.array([0.8, 0.2])
    expected = -(np.log(0.8) + np.log(0.8)) / 2
    assert log_loss(y, prob) == pytest.approx(expected)
    assert neg_log_loss(y, prob) == pytest.approx(-expected)


def test_log_loss_is_finite_for_confident_wrong_prediction() -> None:
    # Clipping keeps a 0/1 prediction on the wrong side finite rather than +inf.
    assert np.isfinite(log_loss(np.array([1.0]), np.array([0.0])))


def test_roc_auc_rank_identity() -> None:
    y = np.array([0.0, 0.0, 1.0, 1.0])
    prob = np.array([0.1, 0.4, 0.35, 0.8])  # 3 of 4 (neg, pos) pairs correctly ordered
    assert roc_auc(y, prob) == pytest.approx(0.75)


def test_roc_auc_perfect_and_random() -> None:
    y = np.array([0.0, 0.0, 1.0, 1.0])
    assert roc_auc(y, np.array([0.1, 0.2, 0.7, 0.9])) == pytest.approx(1.0)
    # All-equal scores -> every pair is a tie -> AUC 0.5 via the average-rank handling.
    assert roc_auc(y, np.full(4, 0.5)) == pytest.approx(0.5)


def test_roc_auc_handles_tied_scores_with_average_ranks() -> None:
    y = np.array([0.0, 1.0, 0.0, 1.0])
    prob = np.array([0.5, 0.5, 0.5, 0.9])  # one clean positive on top, the rest tied
    # Top positive beats both negatives; the tied positive splits its two pairs -> (2 + 1)/4.
    assert roc_auc(y, prob) == pytest.approx(0.75)


def test_roc_auc_single_class_raises() -> None:
    with pytest.raises(ScoringError, match="single-class"):
        roc_auc(np.array([1.0, 1.0]), np.array([0.3, 0.7]))


def test_scores_reject_malformed_inputs() -> None:
    with pytest.raises(ScoringError, match="length mismatch"):
        accuracy(np.array([1.0, 0.0]), np.array([0.5]))
    with pytest.raises(ScoringError, match="binary"):
        log_loss(np.array([2.0, 0.0]), np.array([0.5, 0.5]))
    with pytest.raises(ScoringError, match=r"\[0, 1\]"):
        brier_score(np.array([1.0, 0.0]), np.array([1.5, 0.0]))
    with pytest.raises(ScoringError, match="non-finite"):
        roc_auc(np.array([1.0, 0.0]), np.array([np.nan, 0.5]))
    with pytest.raises(ScoringError, match="empty"):
        accuracy(np.array([]), np.array([]))
