"""Tests for Combinatorial Purged CV (P2.2, Deep Dive #2 §4b.2).

The headline acceptance criteria: CPCV produces the correct number of splits and paths
(φ = C(N,k)·k/N), each path tiles the timeline once, every split stays purged, and the
path-Sharpe distribution summarises correctly.
"""

import math

import numpy as np
import pandas as pd
import pytest

from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution
from quant.research.validation.errors import SplitError
from tests.unit.validation_fakes import overlapping_label_times


def _utc(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    starts = pd.DatetimeIndex(series.index).tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    ends = pd.DatetimeIndex(series).tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    return starts, ends


# --- counts: splits and paths ------------------------------------------------


@pytest.mark.parametrize(
    ("n_groups", "k", "splits", "paths"),
    [(6, 2, 15, 5), (4, 2, 6, 3), (5, 2, 10, 4), (10, 2, 45, 9), (6, 3, 20, 10)],
)
def test_split_and_path_counts(n_groups: int, k: int, splits: int, paths: int) -> None:
    cv = CombinatorialPurgedCV(n_groups, k)
    assert cv.num_splits == splits
    assert cv.num_paths == paths


def test_path_count_equals_phi_identity() -> None:
    # phi = C(N,k)*k/N must equal C(N-1, k-1) for every valid (N, k).
    for n_groups in range(2, 12):
        for k in range(1, n_groups):
            cv = CombinatorialPurgedCV(n_groups, k)
            assert cv.num_paths == math.comb(n_groups, k) * k // n_groups


def test_split_yields_num_splits_each_with_k_test_groups() -> None:
    lt = overlapping_label_times(60)
    cv = CombinatorialPurgedCV(6, 2)
    splits = list(cv.split(lt))
    assert len(splits) == cv.num_splits
    for split in splits:
        assert len(split.test_groups) == 2
        assert set(split.train).isdisjoint(set(split.test))


# --- purge holds across the (possibly non-adjacent) test groups --------------


def test_no_train_observation_overlaps_any_test_run() -> None:
    lt = overlapping_label_times(60, span_steps=3)
    starts, ends = _utc(lt)
    cv = CombinatorialPurgedCV(6, 2, embargo_pct=0.0)
    for split in cv.split(lt):
        test_mask = np.zeros(len(lt), dtype=bool)
        test_mask[split.test] = True
        # Each contiguous run of the (up to 2) test groups defines a span to avoid.
        runs = _contiguous_runs(test_mask)
        for run_start, run_end in runs:
            run_t0 = starts[run_start]
            run_t1 = ends[run_start : run_end + 1].max()
            overlaps = [int(j) for j in split.train if starts[j] <= run_t1 and ends[j] >= run_t0]
            assert overlaps == [], f"train {overlaps} overlap test run [{run_start},{run_end}]"


def _contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    while i < mask.shape[0]:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < mask.shape[0] and mask[j + 1]:
            j += 1
        runs.append((i, j))
        i = j + 1
    return runs


# --- path reconstruction -----------------------------------------------------


def test_each_path_tiles_the_full_timeline_once() -> None:
    # Marker == position: every reconstructed path must equal [0, 1, ..., n-1], proving it
    # covers each observation exactly once, drawn from exactly one split.
    lt = overlapping_label_times(60)
    cv = CombinatorialPurgedCV(6, 2)
    splits = list(cv.split(lt))
    per_split = [pd.Series([float(p) for p in s.test], index=lt.index[s.test]) for s in splits]
    paths = cv.reconstruct_paths(lt, per_split)
    assert len(paths) == cv.num_paths
    for path in paths:
        assert np.array_equal(path.to_numpy(), np.arange(len(lt), dtype="float64"))
        assert list(path.index) == list(lt.index)


def test_paths_draw_each_group_from_a_distinct_split() -> None:
    # Marker == split index: a path's value on group g identifies which split supplied it;
    # across paths, each group is supplied by a different split (the columns of the grid).
    lt = overlapping_label_times(36)
    cv = CombinatorialPurgedCV(6, 2)
    splits = list(cv.split(lt))
    per_split = [
        pd.Series(np.full(s.test.shape[0], float(i)), index=lt.index[s.test])
        for i, s in enumerate(splits)
    ]
    paths = cv.reconstruct_paths(lt, per_split)
    # For each group's position block, collect which split fed it across the 5 paths.
    groups = np.array_split(np.arange(len(lt)), 6)
    for positions in groups:
        suppliers = {float(path.to_numpy()[positions][0]) for path in paths}
        assert len(suppliers) == cv.num_paths  # a distinct split per path


def test_reconstruct_rejects_wrong_number_of_results() -> None:
    lt = overlapping_label_times(60)
    cv = CombinatorialPurgedCV(6, 2)
    with pytest.raises(SplitError, match="expected 15"):
        cv.reconstruct_paths(lt, [pd.Series(dtype="float64")])


# --- path-Sharpe distribution ------------------------------------------------


def test_path_distribution_summary_statistics() -> None:
    cv = CombinatorialPurgedCV(4, 2)
    # Two synthetic paths with Sharpes 2.0 and 1.0.
    paths = [pd.Series([0.01, 0.02, 0.03]), pd.Series([0.0, 0.01, 0.02])]
    dist = cv.path_distribution(paths)
    assert dist.num_paths == 2
    assert dist.path_sharpes == pytest.approx([2.0, 1.0])
    assert dist.median == pytest.approx(1.5)
    assert dist.mean == pytest.approx(1.5)
    assert dist.minimum == pytest.approx(1.0)
    assert dist.fraction_negative == 0.0


def test_path_distribution_flags_negative_paths() -> None:
    cv = CombinatorialPurgedCV(4, 2)
    paths = [pd.Series([0.01, 0.02, 0.03]), pd.Series([-0.01, -0.02, -0.03])]
    dist = cv.path_distribution(paths)
    assert dist.minimum < 0
    assert dist.fraction_negative == pytest.approx(0.5)


def test_single_path_distribution_has_zero_std() -> None:
    dist = PathDistribution(path_sharpes=np.array([1.3]))
    assert dist.std == 0.0
    assert dist.num_paths == 1


def test_run_executes_every_split_and_summarises() -> None:
    lt = overlapping_label_times(60)
    cv = CombinatorialPurgedCV(6, 2)

    def backtest_fn(train: np.ndarray, test: np.ndarray) -> pd.Series:
        # Deterministic varied OOS returns (non-degenerate so Sharpe is defined).
        values = 0.01 * ((test % 3) - 1).astype("float64")
        return pd.Series(values, index=lt.index[test])

    paths, dist = cv.run(lt, backtest_fn)
    assert len(paths) == cv.num_paths
    assert dist.num_paths == cv.num_paths
    assert np.all(np.isfinite(dist.path_sharpes))


# --- validation / fail-loud --------------------------------------------------


def test_too_few_groups_rejected() -> None:
    with pytest.raises(SplitError, match="n_groups"):
        CombinatorialPurgedCV(1, 1)


@pytest.mark.parametrize("k", [0, 6, 7])
def test_test_groups_out_of_range_rejected(k: int) -> None:
    with pytest.raises(SplitError, match="n_test_groups"):
        CombinatorialPurgedCV(6, k)


def test_embargo_out_of_range_rejected() -> None:
    with pytest.raises(SplitError, match="embargo_pct"):
        CombinatorialPurgedCV(6, 2, embargo_pct=1.0)


def test_fewer_observations_than_groups_rejected() -> None:
    lt = overlapping_label_times(4)
    with pytest.raises(SplitError, match="at least"):
        list(CombinatorialPurgedCV(6, 2).split(lt))
