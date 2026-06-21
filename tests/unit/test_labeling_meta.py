"""Tests for meta-labeling (P2.5, Deep Dive #2 §3.4) — primary side + bet/no-bet labels.

With sigma=0.01, k_up=2, k_dn=1.5 and reference 100, the profit-take width is 0.02 and the
stop width 0.015. A long takes profit at 102 / stops at 98.5; a short mirrors it (profit at
98 / stop at 101.5). The meta label is 1 (bet won) or 0 (no-bet).
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import pandas as pd
import pytest

from quant.core.config import LabelingConfig
from quant.data.store.errors import SchemaError
from quant.research.labeling.errors import LabelingInputError
from quant.research.labeling.meta import (
    MetaLabeler,
    MetaLabelSet,
    mean_reversion_side,
    momentum_side,
)
from quant.research.validation import PurgedKFold
from tests.unit.hygiene_fakes import at, bar, frame

D1 = date(2024, 6, 3)


def _labeler() -> MetaLabeler:
    return MetaLabeler(
        LabelingConfig(
            cusum_threshold=0.01,
            barrier_upper_multiple=2.0,
            barrier_lower_multiple=1.5,
            barrier_min_return=0.002,
            vertical_max_hold_bars=0,
        )
    )


def _bars(rows: Sequence[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    return frame([bar("X", ts, o=o, h=h, lo=lo, c=c, v=1000) for ts, o, h, lo, c in rows])


def _vol(bars: pd.DataFrame, sigma: float = 0.01) -> pd.Series:
    return pd.Series(sigma, index=pd.DatetimeIndex(bars["timestamp"]))


def _sides(mapping: Mapping[datetime, int]) -> pd.Series:
    return pd.Series(list(mapping.values()), index=pd.DatetimeIndex(list(mapping.keys())))


def _first_row(bars: pd.DataFrame, event: datetime, side: int, sigma: float = 0.01) -> pd.Series:
    """Meta-label a single event with the given primary side and return its label row."""
    events = pd.DatetimeIndex([event])
    result = _labeler().label(bars, events, _sides({event: side}), _vol(bars, sigma))
    return result.frame.iloc[0]


# --- primary side rules ------------------------------------------------------


def test_momentum_side_signs_the_trailing_move() -> None:
    rising = _bars([(at(D1, 9, 15 + i), 100 + i, 100.5 + i, 99.5 + i, 100 + i) for i in range(5)])
    assert list(momentum_side(rising, 2)) == [0, 0, 1, 1, 1]  # warm-up, then long


def test_momentum_side_is_short_on_a_falling_move() -> None:
    falling = _bars([(at(D1, 9, 15 + i), 100 - i, 100.5 - i, 99.5 - i, 100 - i) for i in range(4)])
    assert list(momentum_side(falling, 1)) == [0, -1, -1, -1]


def test_mean_reversion_side_is_the_negation() -> None:
    rising = _bars([(at(D1, 9, 15 + i), 100 + i, 100.5 + i, 99.5 + i, 100 + i) for i in range(5)])
    assert list(mean_reversion_side(rising, 2)) == [0, 0, -1, -1, -1]


def test_momentum_side_rejects_non_positive_lookback() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.5, 99.5, 100)])
    with pytest.raises(LabelingInputError, match="lookback"):
        momentum_side(bars, 0)


# --- meta labels: long -------------------------------------------------------


def test_long_profit_is_a_bet() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.1, 102.5, 100.0, 101.5),  # profit at 102 hit
            (at(D1, 9, 45), 101.5, 101.8, 101.0, 101.2),
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), 1)
    assert (row["meta_label"], row["barrier"], row["side"]) == (1, "profit", 1)
    assert row["ret"] == pytest.approx(0.02)


def test_long_stop_is_no_bet() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 100.2, 98.0, 98.5),  # stop at 98.5 hit
            (at(D1, 9, 45), 98.5, 99.0, 98.2, 98.8),
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), 1)
    assert (row["meta_label"], row["barrier"]) == (0, "stop")
    assert row["ret"] == pytest.approx(-0.015)


# --- meta labels: short (mirrored) -------------------------------------------


def test_short_profit_when_price_falls() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 100.2, 97.5, 98.0),  # falls to profit at 98
            (at(D1, 9, 45), 98.0, 98.5, 97.9, 98.0),
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), -1)
    assert (row["meta_label"], row["barrier"]) == (1, "profit")
    assert row["ret"] == pytest.approx(0.02)  # side-adjusted: a profitable short is positive


def test_short_stop_when_price_rises() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 102.0, 99.9, 101.5),  # rises to stop at 101.5
            (at(D1, 9, 45), 101.5, 102.0, 101.0, 101.8),
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), -1)
    assert (row["meta_label"], row["barrier"]) == (0, "stop")


def test_short_same_bar_breach_resolves_to_stop() -> None:
    # A short's stop is the upper barrier; a same-bar breach of both -> stop (meta 0).
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 103.0, 97.0, 100.0),  # gaps through both
            (at(D1, 9, 45), 100.0, 100.2, 99.8, 100.0),
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), -1)
    assert (row["meta_label"], row["barrier"]) == (0, "stop")


# --- vertical barrier --------------------------------------------------------


def test_vertical_bet_when_side_adjusted_return_positive() -> None:
    # Long held to session end, ends up: a (small) win -> bet.
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.3, 99.7, 100),
            (at(D1, 9, 30), 100.0, 100.5, 99.8, 100.2),
            (at(D1, 9, 45), 100.2, 100.6, 100.0, 100.4),  # +0.4% at expiry
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), 1)
    assert (row["meta_label"], row["barrier"]) == (1, "vertical")
    assert row["ret"] == pytest.approx(0.004)


def test_vertical_short_bet_when_price_drifts_down() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.3, 99.7, 100),
            (at(D1, 9, 30), 100.0, 100.2, 99.6, 99.9),
            (at(D1, 9, 45), 99.9, 100.0, 99.5, 99.6),  # -0.4% -> short profits
        ]
    )
    row = _first_row(bars, at(D1, 9, 15), -1)
    assert (row["meta_label"], row["barrier"]) == (1, "vertical")
    assert row["ret"] == pytest.approx(0.004)  # side-adjusted (price fell 0.4%, short gains)


# --- skips -------------------------------------------------------------------


def test_flat_side_is_skipped() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.4, 99.6, 100.1) for i in range(3)])
    sides = _sides({at(D1, 9, 15): 0})
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), sides, _vol(bars))
    assert len(result) == 0


def test_event_without_volatility_is_skipped() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.4, 99.6, 100.1) for i in range(3)])
    vol = _vol(bars)
    vol.iloc[0] = float("nan")
    sides = _sides({at(D1, 9, 15): 1})
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), sides, vol)
    assert len(result) == 0


def test_event_on_last_bar_is_skipped() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.4, 99.6, 100), (at(D1, 9, 30), 100, 100.4, 99.6, 100.1)])
    sides = _sides({at(D1, 9, 30): 1})
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 30)]), sides, _vol(bars))
    assert len(result) == 0


# --- accessors / integration -------------------------------------------------


def test_accessors_and_purged_kfold_contract() -> None:
    days = [date(2024, 6, d) for d in (3, 4, 5, 6)]
    rows = []
    events = []
    side_map = {}
    for day in days:
        rows += [
            (at(day, 9, 15), 100, 100.5, 99.5, 100.0),
            (at(day, 9, 30), 100.0, 102.6, 99.7, 101.0),  # long profit hit
            (at(day, 9, 45), 101.0, 101.5, 100.5, 101.0),
        ]
        events.append(at(day, 9, 15))
        side_map[at(day, 9, 15)] = 1
    bars = _bars(rows)
    result = _labeler().label(bars, pd.DatetimeIndex(events), _sides(side_map), _vol(bars))
    assert len(result) == 4
    assert list(result.meta_labels) == [1, 1, 1, 1]
    assert list(result.sides) == [1, 1, 1, 1]
    assert len(list(PurgedKFold(n_splits=2).split(result.label_times))) == 2


def test_empty_inputs_give_empty_labelset() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.4, 99.6, 100)])
    result = _labeler().label(bars, pd.DatetimeIndex([]), _sides({}), _vol(bars))
    assert isinstance(result, MetaLabelSet)
    assert len(result) == 0


# --- validation / fail-loud --------------------------------------------------


def test_sides_not_datetime_indexed_rejected() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.4, 99.6, 100.1) for i in range(3)])
    bad_sides = pd.Series([1, 1, 1])  # RangeIndex
    with pytest.raises(LabelingInputError, match="DatetimeIndex"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), bad_sides, _vol(bars))


def test_event_not_a_bar_rejected() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.4, 99.6, 100.1) for i in range(3)])
    sides = _sides({at(D1, 9, 20): 1})
    with pytest.raises(LabelingInputError, match="bar timestamp"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 20)]), sides, _vol(bars))


def test_duplicate_bar_timestamps_rejected() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.4, 99.6, 100), (at(D1, 9, 15), 100, 100.4, 99.6, 100)])
    sides = _sides({at(D1, 9, 15): 1})
    with pytest.raises(LabelingInputError, match="unique"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), sides, _vol(bars))


def test_bad_schema_rejected() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.4, 99.6, 100)]).drop(columns=["low"])
    with pytest.raises(SchemaError):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _sides({}), _vol(bars))
