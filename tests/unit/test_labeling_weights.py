"""Tests for sample weighting (P2.4, Deep Dive #2 §3.5) — concurrency, uniqueness, etc.

Weights are hand-computed on small overlapping label sets: a label active over bars
``[t0, t1]`` contributes ``1/c_t`` per bar to its average uniqueness, where ``c_t`` is the
concurrency at that bar.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.research.labeling.errors import LabelingInputError
from quant.research.labeling.weights import SampleWeights, time_decay_weights

IST = ZoneInfo("Asia/Kolkata")
_BASE = datetime(2024, 6, 3, 9, 15, tzinfo=IST)


def _t(minute: int) -> datetime:
    return _BASE + timedelta(minutes=minute)


def _bars(n: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([_t(i) for i in range(n)])


def _labels(spans: list[tuple[int, int]]) -> pd.Series:
    """Build label_times from ``(t0_minute, t1_minute)`` spans."""
    starts = pd.DatetimeIndex([_t(s) for s, _ in spans])
    ends = [_t(e) for _, e in spans]
    return pd.Series(ends, index=starts)


# --- concurrency / uniqueness ------------------------------------------------


def test_concurrency_counts_active_labels_per_bar() -> None:
    # A:[0,2], B:[1,3] overlap at bars 1 and 2.
    sw = SampleWeights(_bars(6), _labels([(0, 2), (1, 3)]))
    assert list(sw.concurrency().to_numpy()) == [1, 2, 2, 1, 0, 0]


def test_uniqueness_of_overlapping_labels() -> None:
    sw = SampleWeights(_bars(6), _labels([(0, 2), (1, 3)]))
    # Each label: mean(1/1, 1/2, 1/2) = 2/3.
    assert list(sw.average_uniqueness().round(6)) == [pytest.approx(2 / 3), pytest.approx(2 / 3)]


def test_isolated_label_is_fully_unique() -> None:
    sw = SampleWeights(_bars(4), _labels([(0, 2)]))
    assert sw.average_uniqueness().iloc[0] == pytest.approx(1.0)


def test_nested_label_is_least_unique() -> None:
    # A:[0,3] fully contains B:[1,2]: A=mean(1,.5,.5,1)=0.75, B=mean(.5,.5)=0.5.
    sw = SampleWeights(_bars(5), _labels([(0, 3), (1, 2)]))
    uniqueness = sw.average_uniqueness()
    assert uniqueness.iloc[0] == pytest.approx(0.75)
    assert uniqueness.iloc[1] == pytest.approx(0.5)


def test_disjoint_labels_are_both_fully_unique() -> None:
    sw = SampleWeights(_bars(5), _labels([(0, 1), (2, 3)]))
    assert list(sw.average_uniqueness().round(6)) == [1.0, 1.0]


def test_indicator_matrix_shape_and_content() -> None:
    sw = SampleWeights(_bars(4), _labels([(0, 1), (1, 3)]))
    expected = np.array([[1, 0], [1, 1], [0, 1], [0, 1]], dtype="int8")
    assert np.array_equal(sw.indicator_matrix, expected)


# --- return attribution ------------------------------------------------------


def test_return_attribution_splits_shared_bars() -> None:
    bars = _bars(6)
    sw = SampleWeights(bars, _labels([(0, 2), (1, 3)]))
    prices = pd.Series([100.0, 101.0, 102.0, 101.0, 100.0, 100.5], index=bars)
    raw = sw.return_attribution(prices, normalize=False)
    log_prices = np.log(prices.to_numpy())
    returns = np.diff(log_prices, prepend=log_prices[:1])
    concurrency = sw.concurrency().to_numpy()
    attributed = returns / np.where(concurrency > 0, concurrency, 1)
    assert raw.iloc[0] == pytest.approx(abs(attributed[0:3].sum()))  # label A over bars 0..2
    assert raw.iloc[1] == pytest.approx(abs(attributed[1:4].sum()))  # label B over bars 1..3


def test_return_attribution_normalizes_to_average_one() -> None:
    bars = _bars(6)
    sw = SampleWeights(bars, _labels([(0, 2), (1, 3)]))
    prices = pd.Series([100.0, 101.0, 102.0, 101.0, 100.0, 100.5], index=bars)
    weights = sw.return_attribution(prices, normalize=True)
    assert weights.sum() == pytest.approx(len(weights))  # mean weight 1


def test_return_attribution_requires_full_price_coverage() -> None:
    bars = _bars(6)
    sw = SampleWeights(bars, _labels([(0, 2)]))
    short_prices = pd.Series([100.0, 101.0], index=bars[:2])
    with pytest.raises(LabelingInputError, match="cover every bar"):
        sw.return_attribution(short_prices)


# --- time decay --------------------------------------------------------------


def test_time_decay_identity_when_last_weight_is_one() -> None:
    sw = SampleWeights(_bars(6), _labels([(0, 2), (1, 3)]))
    decay = time_decay_weights(sw.average_uniqueness(), last_weight=1.0)
    assert list(decay.round(6)) == [1.0, 1.0]  # no decay


def test_time_decay_newest_keeps_full_weight() -> None:
    sw = SampleWeights(_bars(6), _labels([(0, 2), (1, 3)]))
    decay = time_decay_weights(sw.average_uniqueness(), last_weight=0.0)
    assert decay.iloc[-1] == pytest.approx(1.0)  # newest -> 1
    assert decay.iloc[0] == pytest.approx(0.5)  # oldest of two equal-uniqueness labels


def test_time_decay_oldest_takes_last_weight() -> None:
    sw = SampleWeights(_bars(6), _labels([(0, 2), (1, 3)]))
    decay = time_decay_weights(sw.average_uniqueness(), last_weight=0.25)
    assert decay.iloc[-1] == pytest.approx(1.0)
    # Two equal-uniqueness labels: oldest is the midpoint of [last_weight, 1].
    assert decay.iloc[0] == pytest.approx((0.25 + 1.0) / 2)


def test_negative_last_weight_zeroes_oldest_observations() -> None:
    sw = SampleWeights(_bars(10), _labels([(0, 0), (2, 2), (4, 4), (6, 6)]))
    decay = time_decay_weights(sw.average_uniqueness(), last_weight=-0.5)
    assert (decay >= 0).all()  # clipped at 0
    assert decay.iloc[-1] == pytest.approx(1.0)
    assert decay.iloc[0] == 0.0  # the oldest fraction is fully decayed


def test_single_label_time_decay_is_one() -> None:
    sw = SampleWeights(_bars(4), _labels([(0, 2)]))
    decay = time_decay_weights(sw.average_uniqueness(), last_weight=0.0)
    assert decay.iloc[0] == pytest.approx(1.0)


def test_invalid_last_weight_rejected() -> None:
    sw = SampleWeights(_bars(4), _labels([(0, 2)]))
    with pytest.raises(LabelingInputError, match="last_weight"):
        time_decay_weights(sw.average_uniqueness(), last_weight=-2.0)


# --- empty -------------------------------------------------------------------


def test_empty_label_set() -> None:
    empty = pd.Series([], index=pd.DatetimeIndex([], tz=IST), dtype="datetime64[ns, Asia/Kolkata]")
    sw = SampleWeights(_bars(4), empty)
    assert len(sw.average_uniqueness()) == 0
    assert list(sw.concurrency().to_numpy()) == [0, 0, 0, 0]  # no labels active anywhere
    assert len(sw.return_attribution(pd.Series(100.0, index=_bars(4)))) == 0
    assert len(time_decay_weights(sw.average_uniqueness())) == 0


# --- validation / fail-loud --------------------------------------------------


def test_bar_times_not_datetime_index_rejected() -> None:
    with pytest.raises(LabelingInputError, match="DatetimeIndex"):
        SampleWeights(pd.Index([0, 1, 2]), _labels([(0, 1)]))  # type: ignore[arg-type]


def test_naive_bar_times_rejected() -> None:
    naive = pd.DatetimeIndex([datetime(2024, 6, 3, 9, 15), datetime(2024, 6, 3, 9, 16)])
    with pytest.raises(LabelingInputError, match="timezone-aware"):
        SampleWeights(naive, _labels([(0, 1)]))


def test_non_unique_bar_times_rejected() -> None:
    with pytest.raises(LabelingInputError, match="unique"):
        SampleWeights(pd.DatetimeIndex([_t(0), _t(0), _t(1)]), _labels([(0, 1)]))


def test_naive_label_index_rejected() -> None:
    naive_idx = pd.DatetimeIndex([datetime(2024, 6, 3, 9, 15)])  # tz-naive t0
    labels = pd.Series([_t(2)], index=naive_idx)
    with pytest.raises(LabelingInputError, match="tz-aware event times"):
        SampleWeights(_bars(4), labels)


def test_non_datetime_label_values_rejected() -> None:
    labels = pd.Series([1, 2], index=pd.DatetimeIndex([_t(0), _t(1)]))  # int t1
    with pytest.raises(LabelingInputError, match="tz-aware datetimes"):
        SampleWeights(_bars(4), labels)


def test_unsorted_bar_times_rejected() -> None:
    with pytest.raises(LabelingInputError, match="sorted"):
        SampleWeights(_bars(4)[np.array([0, 2, 1, 3])], _labels([(0, 1)]))


def test_label_time_not_a_bar_rejected() -> None:
    # t1 at minute 9 is not among the 4 bars.
    with pytest.raises(LabelingInputError, match="must be a bar"):
        SampleWeights(_bars(4), _labels([(0, 9)]))


def test_label_t1_before_t0_rejected() -> None:
    with pytest.raises(LabelingInputError, match="at or after"):
        SampleWeights(_bars(4), _labels([(2, 1)]))


def test_unsorted_label_index_rejected() -> None:
    bars = _bars(6)
    labels = _labels([(0, 2), (1, 3)]).iloc[np.array([1, 0])]  # t0 descending
    with pytest.raises(LabelingInputError, match="sorted and unique"):
        SampleWeights(bars, labels)
