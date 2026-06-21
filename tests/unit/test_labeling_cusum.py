"""Tests for the symmetric CUSUM event sampler (P2.3, Deep Dive #2 §3.3)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.research.labeling.cusum import cusum_events
from quant.research.labeling.errors import LabelingInputError
from tests.unit.hygiene_fakes import at

D1 = date(2024, 6, 3)


def _prices(values: list[float]) -> pd.Series:
    """A close-price Series on consecutive IST minutes."""
    index = pd.DatetimeIndex([at(D1, 9, 15 + i) for i in range(len(values))])
    return pd.Series(values, index=index)


def test_up_move_triggers_event() -> None:
    # ln(101.5/100) ~ 0.0149 clears the 1% threshold on the third bar.
    events = cusum_events(_prices([100.0, 100.0, 101.5]), 0.01)
    assert list(events) == [at(D1, 9, 17)]


def test_down_move_triggers_event() -> None:
    events = cusum_events(_prices([100.0, 100.0, 98.5]), 0.01)
    assert list(events) == [at(D1, 9, 17)]


def test_no_event_below_threshold() -> None:
    # Small, partly offsetting moves never accumulate to 1%.
    events = cusum_events(_prices([100.0, 100.3, 100.1, 100.4]), 0.01)
    assert list(events) == []


def test_accumulator_resets_after_an_event() -> None:
    # Two separate ~1.5% up-moves, with a flat bar between, fire two events.
    events = cusum_events(_prices([100.0, 101.5, 101.5, 103.0]), 0.01)
    assert list(events) == [at(D1, 9, 16), at(D1, 9, 18)]


def test_dynamic_threshold_series() -> None:
    prices = _prices([100.0, 100.0, 101.5])
    # A high threshold on the move bar suppresses the event; a low one admits it.
    high = pd.Series([0.01, 0.01, 0.05], index=prices.index)
    low = pd.Series([0.01, 0.01, 0.005], index=prices.index)
    assert list(cusum_events(prices, high)) == []
    assert list(cusum_events(prices, low)) == [at(D1, 9, 17)]


def test_symmetric_up_then_down() -> None:
    events = cusum_events(_prices([100.0, 101.5, 101.5, 99.8]), 0.01)
    assert list(events) == [at(D1, 9, 16), at(D1, 9, 18)]  # one up, one down


def test_empty_and_single_bar_have_no_events() -> None:
    empty = pd.Series([], dtype="float64", index=pd.DatetimeIndex([]))
    assert list(cusum_events(empty, 0.01)) == []
    assert list(cusum_events(_prices([100.0]), 0.01)) == []


# --- validation / fail-loud --------------------------------------------------


def test_non_datetime_index_rejected() -> None:
    with pytest.raises(LabelingInputError, match="DatetimeIndex"):
        cusum_events(pd.Series([100.0, 101.0], index=[0, 1]), 0.01)


def test_naive_index_rejected() -> None:
    naive = pd.Series([100.0, 101.0], index=pd.DatetimeIndex(["2024-06-03", "2024-06-04"]))
    with pytest.raises(LabelingInputError, match="timezone-aware"):
        cusum_events(naive, 0.01)


def test_unsorted_index_rejected() -> None:
    prices = _prices([100.0, 101.0, 102.0]).iloc[np.array([0, 2, 1])]
    with pytest.raises(LabelingInputError, match="sorted"):
        cusum_events(prices, 0.01)


def test_non_unique_index_rejected() -> None:
    dup = pd.Series([100.0, 101.0], index=pd.DatetimeIndex([at(D1, 9, 15), at(D1, 9, 15)]))
    with pytest.raises(LabelingInputError, match="unique"):
        cusum_events(dup, 0.01)


def test_non_positive_price_rejected() -> None:
    with pytest.raises(LabelingInputError, match="positive"):
        cusum_events(_prices([100.0, 0.0, 101.0]), 0.01)


def test_non_positive_scalar_threshold_rejected() -> None:
    with pytest.raises(LabelingInputError, match="threshold must be positive"):
        cusum_events(_prices([100.0, 101.0]), 0.0)


def test_misaligned_threshold_series_rejected() -> None:
    prices = _prices([100.0, 101.0, 102.0])
    bad = pd.Series([0.01, 0.01], index=prices.index[:2])
    with pytest.raises(LabelingInputError, match="indexed exactly like prices"):
        cusum_events(prices, bad)


def test_non_positive_threshold_series_rejected() -> None:
    prices = _prices([100.0, 101.0])
    with pytest.raises(LabelingInputError, match="strictly positive"):
        cusum_events(prices, pd.Series([0.01, 0.0], index=prices.index))
