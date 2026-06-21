"""Tests for purged k-fold + embargo cross-validation (P2.1, Deep Dive #2 §4b.1).

The headline acceptance criterion: purge/embargo provably removes any train/test label
overlap. The closed-window overlap test (``a0 <= b1 and b0 <= a1``) is asserted directly
against the realistic, overlapping-label case.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.research.validation.errors import SplitError
from quant.research.validation.splits import PurgedKFold, embargo_size
from tests.unit.validation_fakes import label_times, overlapping_label_times

IST = ZoneInfo("Asia/Kolkata")
BASE = datetime(2024, 1, 1, 9, 15, tzinfo=IST)


def _utc(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Return (t0, t1) as UTC datetime64 arrays for hand-checking the overlap invariant."""
    starts = pd.DatetimeIndex(series.index).tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    ends = pd.DatetimeIndex(series).tz_convert("UTC").to_numpy(dtype="datetime64[ns]")
    return starts, ends


# --- structure ---------------------------------------------------------------


def test_yields_n_splits_folds() -> None:
    lt = overlapping_label_times(20)
    splitter = PurgedKFold(n_splits=5)
    assert splitter.n_splits == 5
    assert len(list(splitter.split(lt))) == 5


def test_test_blocks_partition_every_observation_once() -> None:
    # Each observation appears in exactly one fold's test set (a true k-fold partition).
    lt = overlapping_label_times(20)
    seen: list[int] = []
    for fold in PurgedKFold(n_splits=4).split(lt):
        seen.extend(int(i) for i in fold.test)
    assert sorted(seen) == list(range(20))


def test_test_blocks_are_contiguous_in_time() -> None:
    lt = overlapping_label_times(20)
    for fold in PurgedKFold(n_splits=5).split(lt):
        assert list(fold.test) == list(range(int(fold.test[0]), int(fold.test[-1]) + 1))


def test_train_and_test_are_disjoint() -> None:
    lt = overlapping_label_times(20)
    for fold in PurgedKFold(n_splits=5, embargo_pct=0.05).split(lt):
        assert set(fold.train).isdisjoint(set(fold.test))


# --- the core invariant: no overlap ------------------------------------------


def test_purge_removes_all_train_test_overlap() -> None:
    # With 2-step overlapping label windows, no purged train window may intersect the
    # test block's span [min t0_test, max t1_test].
    lt = overlapping_label_times(24, span_steps=3)
    starts, ends = _utc(lt)
    for fold in PurgedKFold(n_splits=6, embargo_pct=0.0).split(lt):
        test_t0 = starts[fold.test].min()
        test_t1 = ends[fold.test].max()
        overlaps = [int(j) for j in fold.train if starts[j] <= test_t1 and ends[j] >= test_t0]
        assert overlaps == [], f"train obs {overlaps} overlap the test span"


def test_purge_keeps_more_than_embargo_for_non_overlapping_labels() -> None:
    # Point labels (t1 == t0) cannot overlap across folds, so with no embargo the only
    # excluded observations are the test block itself.
    pairs = [(BASE + timedelta(days=i), BASE + timedelta(days=i)) for i in range(12)]
    lt = label_times(pairs)
    for fold in PurgedKFold(n_splits=4, embargo_pct=0.0).split(lt):
        assert len(fold.train) + len(fold.test) == 12  # nothing purged beyond the test block


# --- embargo -----------------------------------------------------------------


def test_embargo_size_is_floor_of_fraction() -> None:
    assert embargo_size(100, 0.05) == 5
    assert embargo_size(10, 0.25) == 2  # floor(2.5)
    assert embargo_size(10, 0.0) == 0


def test_embargo_drops_observations_after_the_test_block() -> None:
    # Point labels so purging alone removes nothing; the embargo is then the only thing
    # that drops post-test observations. n=10, 5 folds, embargo_pct=0.2 -> embargo=2.
    pairs = [(BASE + timedelta(days=i), BASE + timedelta(days=i)) for i in range(10)]
    lt = label_times(pairs)
    folds = list(PurgedKFold(n_splits=5, embargo_pct=0.2).split(lt))
    # First fold tests [0,1]; the 2 observations immediately after (2,3) are embargoed.
    first = folds[0]
    assert {int(i) for i in first.test} == {0, 1}
    assert 2 not in set(first.train) and 3 not in set(first.train)
    assert {int(i) for i in first.train} == {4, 5, 6, 7, 8, 9}


def test_zero_embargo_keeps_immediate_neighbour_for_point_labels() -> None:
    pairs = [(BASE + timedelta(days=i), BASE + timedelta(days=i)) for i in range(10)]
    lt = label_times(pairs)
    first = next(iter(PurgedKFold(n_splits=5, embargo_pct=0.0).split(lt)))
    assert 2 in {int(i) for i in first.train}  # neighbour kept when no embargo


# --- validation / fail-loud --------------------------------------------------


def test_n_splits_below_two_rejected() -> None:
    with pytest.raises(SplitError, match="n_splits"):
        PurgedKFold(n_splits=1)


@pytest.mark.parametrize("bad", [-0.1, 1.0, 1.5])
def test_embargo_pct_out_of_range_rejected(bad: float) -> None:
    with pytest.raises(SplitError, match="embargo_pct"):
        PurgedKFold(n_splits=3, embargo_pct=bad)


def test_more_folds_than_observations_rejected() -> None:
    lt = overlapping_label_times(3)
    with pytest.raises(SplitError, match="at least"):
        list(PurgedKFold(n_splits=5).split(lt))


def test_non_datetime_index_rejected() -> None:
    lt = pd.Series([1, 2, 3], index=[0, 1, 2])
    with pytest.raises(SplitError, match="DatetimeIndex"):
        list(PurgedKFold(n_splits=2).split(lt))


def test_naive_index_rejected() -> None:
    idx = pd.DatetimeIndex([datetime(2024, 1, 1), datetime(2024, 1, 2)])  # tz-naive
    lt = pd.Series(idx, index=idx)
    with pytest.raises(SplitError, match="timezone-aware"):
        list(PurgedKFold(n_splits=2).split(lt))


def test_unsorted_index_rejected() -> None:
    lt = overlapping_label_times(6)
    shuffled = lt.iloc[np.array([0, 2, 1, 3, 4, 5])]
    with pytest.raises(SplitError, match="sorted"):
        list(PurgedKFold(n_splits=2).split(shuffled))


def test_duplicate_index_rejected() -> None:
    t0 = BASE
    lt = label_times([(t0, t0 + timedelta(days=1)), (t0, t0 + timedelta(days=1))])
    with pytest.raises(SplitError, match="unique"):
        list(PurgedKFold(n_splits=2).split(lt))


def test_non_datetime_values_rejected() -> None:
    idx = pd.DatetimeIndex([BASE + timedelta(days=i) for i in range(4)])
    lt = pd.Series([1, 2, 3, 4], index=idx)  # values are ints, not label-resolution times
    with pytest.raises(SplitError, match="datetimes"):
        list(PurgedKFold(n_splits=2).split(lt))


def test_label_end_before_start_rejected() -> None:
    t0 = BASE + timedelta(days=5)
    lt = label_times([(BASE, BASE + timedelta(days=1)), (t0, t0 - timedelta(days=1))])
    with pytest.raises(SplitError, match="t1"):
        list(PurgedKFold(n_splits=2).split(lt))
