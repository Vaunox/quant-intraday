"""Tests for the triple-barrier labeler (P2.3, Deep Dive #2 §3.2).

Barriers are hand-computed: with sigma=0.01, k_up=2, k_dn=1.5 and a reference close of 100,
the profit-take sits at 102.0 and the stop at 98.5. Outcomes are checked on synthetic OHLC
paths, including the conservative same-bar tie, vol scaling, the cost-hurdle floor, and the
session-end vertical barrier.
"""

from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd
import pytest

from quant.core.config import LabelingConfig
from quant.data.store.errors import SchemaError
from quant.research.labeling.errors import LabelingInputError
from quant.research.labeling.triple_barrier import LabelSet, TripleBarrierLabeler
from quant.research.validation import PurgedKFold
from tests.unit.hygiene_fakes import at, bar, frame

D1 = date(2024, 6, 3)  # Mon
D2 = date(2024, 6, 4)  # Tue


def _labeler(
    *, k_up: float = 2.0, k_dn: float = 1.5, min_return: float = 0.002, max_hold: int = 0
) -> TripleBarrierLabeler:
    return TripleBarrierLabeler(
        LabelingConfig(
            cusum_threshold=0.01,
            barrier_upper_multiple=k_up,
            barrier_lower_multiple=k_dn,
            barrier_min_return=min_return,
            vertical_max_hold_bars=max_hold,
        )
    )


def _bars(rows: Sequence[tuple[datetime, float, float, float, float]]) -> pd.DataFrame:
    """Build bars from ``(timestamp, open, high, low, close)`` rows."""
    return frame([bar("X", ts, o=o, h=h, lo=lo, c=c, v=1000) for ts, o, h, lo, c in rows])


def _vol(bars: pd.DataFrame, sigma: float) -> pd.Series:
    """A constant trailing-volatility Series aligned to the bars' timestamps."""
    return pd.Series(sigma, index=pd.DatetimeIndex(bars["timestamp"]))


# --- the three barriers ------------------------------------------------------


def test_upper_barrier_gives_long_label() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.1, 102.5, 100.0, 101.5),  # high 102.5 >= 102 -> +1
            (at(D1, 9, 45), 101.5, 101.8, 101.0, 101.2),
        ]
    )
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01))
    row = result.frame.iloc[0]
    assert row["label"] == 1
    assert row["barrier"] == "upper"
    assert row["exit_time"] == at(D1, 9, 30)  # first touch
    assert row["ret"] == pytest.approx(0.02)  # exits at the +2 sigma barrier


def test_lower_barrier_gives_short_label() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 100.2, 98.0, 98.5),  # low 98.0 <= 98.5 -> -1
            (at(D1, 9, 45), 98.5, 99.0, 98.2, 98.8),
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01)).frame.iloc[0]
    assert row["label"] == -1
    assert row["barrier"] == "lower"
    assert row["ret"] == pytest.approx(-0.015)  # exits at the -1.5 sigma barrier


def test_vertical_barrier_labels_by_sign() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.3, 99.7, 100),
            (at(D1, 9, 30), 100.0, 100.5, 99.8, 100.2),
            (at(D1, 9, 45), 100.2, 100.6, 100.0, 100.4),  # ends +0.4%, no barrier hit
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01)).frame.iloc[0]
    assert row["label"] == 1
    assert row["barrier"] == "vertical"
    assert row["exit_time"] == at(D1, 9, 45)  # the session's last bar
    assert row["ret"] == pytest.approx(0.004)


def test_vertical_exactly_flat_is_zero() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.3, 99.7, 100),
            (at(D1, 9, 30), 100.0, 100.4, 99.6, 100),  # returns exactly to 100 -> label 0
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01)).frame.iloc[0]
    assert row["label"] == 0
    assert row["barrier"] == "vertical"


# --- path dependence ---------------------------------------------------------


def test_same_bar_breach_resolves_to_stop() -> None:
    # A bar that gaps through both barriers: order unknown -> the stop wins (conservative).
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 103.0, 97.0, 100.0),  # high>=102 AND low<=98.5
            (at(D1, 9, 45), 100.0, 100.2, 99.8, 100.0),
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01)).frame.iloc[0]
    assert row["label"] == -1
    assert row["barrier"] == "lower"


def test_first_touch_wins() -> None:
    # Upper touched on bar 2; a later lower breach must not override the earlier +1.
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.5, 102.5, 100.2, 102.0),  # +1 here
            (at(D1, 9, 45), 101.0, 101.2, 98.0, 98.2),  # would be a stop, but later
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01)).frame.iloc[0]
    assert (row["label"], row["barrier"], row["exit_time"]) == (1, "upper", at(D1, 9, 30))


# --- volatility scaling / cost floor -----------------------------------------


def test_higher_volatility_widens_barriers_to_vertical() -> None:
    # The same path that touched at sigma=0.01 stays inside far-out barriers at sigma=0.5.
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.1, 102.5, 100.0, 101.5),
            (at(D1, 9, 45), 101.5, 101.8, 101.0, 101.2),
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.5)).frame.iloc[0]
    assert row["barrier"] == "vertical"  # +-2 sigma is now +-100% / -75%, never touched


def test_min_return_floor_applies_in_low_volatility() -> None:
    # sigma=0.0001 -> k_up*sigma=0.0002 < 0.002 floor, so the barrier is the 0.2% floor.
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.05, 99.95, 100),
            (at(D1, 9, 30), 100.0, 100.25, 99.99, 100.2),  # high 100.25 >= 100.2 floor barrier
            (at(D1, 9, 45), 100.2, 100.3, 100.1, 100.2),
        ]
    )
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.0001))
    row = result.frame.iloc[0]
    assert row["label"] == 1
    assert row["ret"] == pytest.approx(0.002)  # the cost-hurdle floor, not 2*0.0001


# --- vertical barrier = session end ------------------------------------------


def test_vertical_barrier_is_session_end_not_next_day() -> None:
    # Far barriers; the position must resolve at session A's last bar, never carry into B.
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.3, 99.8, 100.1),
            (at(D1, 9, 45), 100.1, 100.4, 99.9, 100.2),  # last bar of session A
            (at(D2, 9, 15), 200, 200.5, 199.5, 200.3),  # session B (next day) - off limits
            (at(D2, 9, 45), 200.3, 200.6, 200.0, 200.4),
        ]
    )
    row = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.5)).frame.iloc[0]
    assert row["barrier"] == "vertical"
    assert row["exit_time"] == at(D1, 9, 45)  # session A's close, not D2


def test_max_hold_caps_the_vertical_barrier() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.3, 99.8, 100.1) for i in range(5)])
    row = (
        _labeler(k_up=50, k_dn=50, max_hold=2)  # huge barriers -> always vertical
        .label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01))
        .frame.iloc[0]
    )
    assert row["exit_time"] == at(D1, 9, 17)  # event + 2 bars, not the session end at 09:19


# --- skips -------------------------------------------------------------------


def test_event_without_volatility_is_skipped() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.3, 99.8, 100.1) for i in range(3)])
    vol = _vol(bars, 0.01)
    vol.iloc[0] = float("nan")  # warm-up: no sigma at the event bar
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), vol)
    assert len(result) == 0


def test_event_on_last_session_bar_is_skipped() -> None:
    bars = _bars(
        [(at(D1, 9, 15), 100, 100.3, 99.8, 100.1), (at(D1, 9, 30), 100.1, 100.4, 99.9, 100.2)]
    )
    # Event on the final bar has no room to hold to a vertical barrier.
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 30)]), _vol(bars, 0.01))
    assert len(result) == 0


# --- accessors / integration -------------------------------------------------


def test_label_times_and_sides_accessors() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.1, 102.5, 100.0, 101.5),
            (at(D1, 9, 45), 101.5, 101.8, 101.0, 101.2),
        ]
    )
    result = _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01))
    assert list(result.label_times.index) == [at(D1, 9, 15)]  # indexed by event t0
    assert list(result.label_times) == [at(D1, 9, 30)]  # value is the resolution t1
    assert list(result.sides) == [1]


def test_label_times_feed_purged_kfold() -> None:
    # Four single-event sessions -> label_times accepted by the CV splitter (the contract).
    days = [date(2024, 6, d) for d in (3, 4, 5, 6)]  # Mon-Thu
    rows = []
    events = []
    for day in days:
        rows += [
            (at(day, 9, 15), 100, 100.3, 99.8, 100.0),
            (at(day, 9, 30), 100.0, 100.4, 99.7, 100.1),
            (at(day, 9, 45), 100.1, 100.5, 99.9, 100.2),
        ]
        events.append(at(day, 9, 15))
    bars = _bars(rows)
    result = _labeler().label(bars, pd.DatetimeIndex(events), _vol(bars, 0.01))
    assert len(result) == 4
    folds = list(PurgedKFold(n_splits=2).split(result.label_times))
    assert len(folds) == 2  # the splitter consumes label_times without error


def test_empty_bars_or_events_give_empty_labelset() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.3, 99.8, 100.0)])
    assert len(_labeler().label(bars, pd.DatetimeIndex([]), _vol(bars, 0.01))) == 0
    empty_result = _labeler().label(frame([]), pd.DatetimeIndex([]), pd.Series(dtype="float64"))
    assert isinstance(empty_result, LabelSet)
    assert len(empty_result) == 0


def test_multiple_events_labeled_independently() -> None:
    bars = _bars(
        [
            (at(D1, 9, 15), 100, 100.4, 99.6, 100),
            (at(D1, 9, 30), 100.0, 102.5, 99.9, 101.5),  # event-1 (09:15) hits upper here
            (at(D1, 9, 45), 101.5, 101.7, 98.0, 98.2),  # event-2 (09:30) hits lower here
            (at(D1, 9, 55), 98.2, 98.5, 97.9, 98.0),
        ]
    )
    events = pd.DatetimeIndex([at(D1, 9, 15), at(D1, 9, 30)])
    result = _labeler().label(bars, events, _vol(bars, 0.01))
    assert list(result.sides) == [1, -1]


# --- validation / fail-loud --------------------------------------------------


def test_event_not_a_bar_timestamp_rejected() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.3, 99.8, 100.1) for i in range(3)])
    with pytest.raises(LabelingInputError, match="bar timestamp"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 20)]), _vol(bars, 0.01))


def test_events_not_datetime_index_rejected() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.3, 99.8, 100.1) for i in range(3)])
    with pytest.raises(LabelingInputError, match="DatetimeIndex"):
        _labeler().label(bars, pd.Index([1, 2]), _vol(bars, 0.01))  # type: ignore[arg-type]


def test_volatility_not_datetime_indexed_rejected() -> None:
    bars = _bars([(at(D1, 9, 15 + i), 100, 100.3, 99.8, 100.1) for i in range(3)])
    bad_vol = pd.Series([0.01, 0.01, 0.01])  # default RangeIndex
    with pytest.raises(LabelingInputError, match="DatetimeIndex"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), bad_vol)


def test_duplicate_bar_timestamps_rejected() -> None:
    bars = _bars(
        [(at(D1, 9, 15), 100, 100.3, 99.8, 100.0), (at(D1, 9, 15), 100, 100.3, 99.8, 100.0)]
    )
    with pytest.raises(LabelingInputError, match="unique"):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), _vol(bars, 0.01))


def test_bad_schema_rejected() -> None:
    bars = _bars([(at(D1, 9, 15), 100, 100.3, 99.8, 100.0)]).drop(columns=["high"])
    with pytest.raises(SchemaError):
        _labeler().label(bars, pd.DatetimeIndex([at(D1, 9, 15)]), pd.Series(dtype="float64"))
