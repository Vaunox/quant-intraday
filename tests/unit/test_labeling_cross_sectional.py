"""Tests for cross-sectional forward-return labeling (P3X.3) on synthetic panels."""

import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.labeling.cross_sectional import (
    build_cross_sectional_labels,
    cross_sectional_decile,
    forward_total_return,
    month_end_rebalance_dates,
)
from quant.research.labeling.errors import LabelingInputError

# Five symbols with constant daily growth rates → constant, distinct forward returns, so the
# cross-sectional ordering is D < A < E < B < C at every rebalance date.
_RATES = {"A": 1.0, "B": 1.01, "C": 1.02, "D": 0.99, "E": 1.005}
_N = 70


def _panel_and_dates() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    dates = pd.date_range("2020-01-01", periods=_N, freq="B", tz=IST)
    panel = pd.DataFrame(
        {s: [100.0 * (r**i) for i in range(_N)] for s, r in _RATES.items()}, index=dates
    )
    return panel, dates


def test_month_end_rebalance_dates_picks_last_session_of_each_month() -> None:
    panel, dates = _panel_and_dates()
    reb = month_end_rebalance_dates(dates)
    for d in reb:
        same_month = dates[(dates.year == d.year) & (dates.month == d.month)]
        assert d == same_month.max()
    assert pd.Timestamp("2020-01-31", tz=IST) in set(reb)


def test_forward_total_return_value() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 50]]
    fwd = forward_total_return(panel, reb, horizon=5)
    # close[d+5]/close[d] - 1 = rate**5 - 1, constant per symbol.
    assert fwd.loc[reb[0], "C"] == pytest.approx(1.02**5 - 1.0)
    assert fwd.loc[reb[1], "D"] == pytest.approx(0.99**5 - 1.0)


def test_forward_return_uses_only_entry_and_exit_close() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 50]]
    base = forward_total_return(panel, reb, horizon=5).at[reb[0], "C"]
    # Perturbing a PRE-rebalance bar (pos 9, before the pos-10 rebalance) leaves the label intact.
    pre = panel.copy()
    pre.at[dates[9], "C"] = 1.0  # a value clearly different from the real ~100+ price
    assert forward_total_return(pre, reb, horizon=5).at[reb[0], "C"] == pytest.approx(base)
    # Perturbing the EXIT bar (pos 15 = 10 + 5) changes it — forward dependence is real.
    post = panel.copy()
    post.at[dates[15], "C"] = 1.0
    assert forward_total_return(post, reb, horizon=5).at[reb[0], "C"] != pytest.approx(base)


def test_tail_rebalance_without_forward_window_is_dropped() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 68]]  # 68 + 5 = 73 > 70 → no forward window
    labels = build_cross_sectional_labels(panel, reb, horizon=5, n_quantiles=5)
    assert dates[68] not in set(labels.rebalance_dates)
    assert dates[10] in set(labels.rebalance_dates)


def test_cross_sectional_decile_orders_within_universe() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 50]]
    labels = build_cross_sectional_labels(panel, reb, horizon=5, n_quantiles=5)
    d0 = labels.decile_rank.loc[reb[0]]
    # Ordering D < A < E < B < C → deciles 0,1,2,3,4.
    assert (d0["D"], d0["A"], d0["E"], d0["B"], d0["C"]) == (0, 1, 2, 3, 4)


def test_universe_mask_excludes_nonmembers_from_ranking() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 50]]
    mask = pd.DataFrame(True, index=reb, columns=panel.columns)
    mask.loc[reb[0], "C"] = False  # drop the top name at the first rebalance
    labels = build_cross_sectional_labels(panel, reb, horizon=5, n_quantiles=5, universe_mask=mask)
    assert pd.isna(labels.forward_return.loc[reb[0], "C"])
    assert pd.isna(labels.decile_rank.loc[reb[0], "C"])
    # Remaining four (D<A<E<B) re-rank among themselves → B is now top.
    assert labels.decile_rank.loc[reb[0], "B"] == 4
    # An unaffected rebalance still ranks C top.
    assert labels.decile_rank.loc[reb[1], "C"] == 4


def test_label_times_span_is_horizon_sessions() -> None:
    panel, dates = _panel_and_dates()
    reb = dates[[10, 30, 50]]
    labels = build_cross_sectional_labels(panel, reb, horizon=5, n_quantiles=5)
    # t1 for the pos-10 rebalance is the pos-15 session.
    assert labels.label_times.loc[reb[0]] == dates[15]


def test_invalid_inputs_raise() -> None:
    panel, dates = _panel_and_dates()
    with pytest.raises(LabelingInputError):
        forward_total_return(panel, dates[[10]], horizon=0)
    with pytest.raises(LabelingInputError):
        cross_sectional_decile(panel, n_quantiles=1)
    unknown = pd.DatetimeIndex([pd.Timestamp("1999-01-01", tz=IST)])
    with pytest.raises(LabelingInputError):
        forward_total_return(panel, unknown, horizon=5)
