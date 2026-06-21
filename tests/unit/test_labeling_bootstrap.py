"""Tests for the uniqueness-aware sequential bootstrap (P2.4, Deep Dive #2 §3.5)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.research.labeling.bootstrap import (
    average_uniqueness_of_sample,
    sequential_bootstrap,
)
from quant.research.labeling.errors import LabelingInputError
from quant.research.labeling.weights import SampleWeights

IST = ZoneInfo("Asia/Kolkata")
_BASE = datetime(2024, 6, 3, 9, 0, tzinfo=IST)


def _t(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _overlapping_matrix() -> np.ndarray:
    """One isolated label + five that heavily overlap (the redundant case)."""
    panel = pd.DatetimeIndex([_t(i) for i in range(30)])
    starts = [_t(0), _t(10), _t(11), _t(12), _t(13), _t(14)]
    ends = [_t(1), _t(20), _t(20), _t(20), _t(20), _t(20)]
    label_times = pd.Series(ends, index=pd.DatetimeIndex(starts))
    return SampleWeights(panel, label_times).indicator_matrix


# --- behaviour ---------------------------------------------------------------


def test_is_deterministic_for_a_seed() -> None:
    matrix = _overlapping_matrix()
    first = sequential_bootstrap(matrix, 6, rng=np.random.default_rng(7))
    second = sequential_bootstrap(matrix, 6, rng=np.random.default_rng(7))
    assert np.array_equal(first, second)


def test_draws_valid_indices() -> None:
    matrix = _overlapping_matrix()
    drawn = sequential_bootstrap(matrix, 20, rng=np.random.default_rng(1))
    assert drawn.shape == (20,)
    assert drawn.min() >= 0 and drawn.max() < matrix.shape[1]


def test_default_sample_size_is_label_count() -> None:
    matrix = _overlapping_matrix()
    drawn = sequential_bootstrap(matrix, rng=np.random.default_rng(2))
    assert drawn.shape == (matrix.shape[1],)  # = number of labels


def test_samples_by_uniqueness_beating_uniform() -> None:
    # The defining property: a sequential-bootstrap sample carries more independent
    # information (higher average uniqueness) than a uniform-random one, on overlapping data.
    matrix = _overlapping_matrix()
    n_labels = matrix.shape[1]
    seq_scores = []
    uniform_scores = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        seq = sequential_bootstrap(matrix, n_labels, rng=rng)
        uniform = np.asarray(rng.choice(n_labels, size=n_labels), dtype=np.intp)
        seq_scores.append(average_uniqueness_of_sample(matrix, seq))
        uniform_scores.append(average_uniqueness_of_sample(matrix, uniform))
    assert np.mean(seq_scores) > np.mean(uniform_scores)


def test_average_uniqueness_of_isolated_sample_is_one() -> None:
    # A sample of distinct, non-overlapping labels is fully unique.
    panel = pd.DatetimeIndex([_t(i) for i in range(6)])
    label_times = pd.Series([_t(1), _t(3), _t(5)], index=pd.DatetimeIndex([_t(0), _t(2), _t(4)]))
    matrix = SampleWeights(panel, label_times).indicator_matrix
    assert average_uniqueness_of_sample(matrix, np.array([0, 1, 2])) == pytest.approx(1.0)


def test_average_uniqueness_drops_with_repeats() -> None:
    panel = pd.DatetimeIndex([_t(i) for i in range(6)])
    label_times = pd.Series([_t(1), _t(3)], index=pd.DatetimeIndex([_t(0), _t(2)]))
    matrix = SampleWeights(panel, label_times).indicator_matrix
    # Drawing the same label twice halves its uniqueness (it now overlaps itself).
    assert average_uniqueness_of_sample(matrix, np.array([0, 0])) == pytest.approx(0.5)


# --- validation / fail-loud --------------------------------------------------


def test_non_2d_matrix_rejected() -> None:
    with pytest.raises(LabelingInputError, match="bars, labels"):
        sequential_bootstrap(np.zeros(10, dtype="int8"), rng=np.random.default_rng(0))


def test_zero_labels_rejected() -> None:
    with pytest.raises(LabelingInputError, match="labels>=1"):
        sequential_bootstrap(np.zeros((10, 0), dtype="int8"), rng=np.random.default_rng(0))


def test_zero_length_label_rejected() -> None:
    # A label that spans no bars (an all-zero column) cannot be weighted.
    matrix = np.array([[1, 0], [1, 0]], dtype="int8")
    with pytest.raises(LabelingInputError, match="at least one bar"):
        sequential_bootstrap(matrix, rng=np.random.default_rng(0))


def test_non_positive_sample_size_rejected() -> None:
    matrix = _overlapping_matrix()
    with pytest.raises(LabelingInputError, match="n_samples"):
        sequential_bootstrap(matrix, 0, rng=np.random.default_rng(0))


def test_empty_sample_uniqueness_rejected() -> None:
    matrix = _overlapping_matrix()
    with pytest.raises(LabelingInputError, match="at least one"):
        average_uniqueness_of_sample(matrix, np.array([], dtype="intp"))
