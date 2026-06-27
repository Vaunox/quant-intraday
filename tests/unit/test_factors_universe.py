"""Tests for the liquidity-ranked survivorship-correct universe (P3X.1c)."""

import pandas as pd
import pytest

from quant.research.factors.errors import FactorError
from quant.research.factors.universe import (
    average_daily_value,
    liquidity_universe,
    load_sector_map,
)


def test_average_daily_value_is_trailing_median() -> None:
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    panel = pd.DataFrame({"X": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=dates)
    adv = average_daily_value(panel, window=3)
    assert adv["X"].iloc[2] == pytest.approx(2.0)  # median(1,2,3)
    assert adv["X"].iloc[4] == pytest.approx(4.0)  # median(3,4,5)


def test_liquidity_universe_selects_top_n_and_screens_history() -> None:
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    panel = pd.DataFrame(index=dates, dtype=float)
    panel["A"], panel["B"], panel["C"], panel["D"] = 10e6, 8e6, 6e6, 4e6
    panel["F"] = float("nan")  # a fat-ADV newcomer with too little history
    panel.loc[dates[-5:], "F"] = 100e6

    rebalances = pd.DatetimeIndex([dates[-1]])
    eligible = liquidity_universe(
        panel, rebalances, top_n=3, adv_window=126, min_history_sessions=252
    )
    row = eligible.iloc[0]
    assert bool(row["A"]) and bool(row["B"]) and bool(row["C"])  # top 3 by ADV
    assert not bool(row["D"])  # rank 4 > top_n
    assert not bool(row["F"])  # high ADV but fails the history screen
    assert int(row.sum()) == 3


def test_load_sector_map(tmp_path: object) -> None:
    csv = tmp_path / "ind_nifty500list.csv"  # type: ignore[operator]
    csv.write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n"
        "Reliance,Energy,RELIANCE,EQ,IN1\n"
        "TCS,IT,TCS,EQ,IN2\n"
    )
    mapping = load_sector_map(str(csv))
    assert mapping == {"RELIANCE": "Energy", "TCS": "IT"}


def test_invalid_inputs_raise() -> None:
    panel = pd.DataFrame({"A": [1.0]}, index=pd.date_range("2020-01-01", periods=1))
    with pytest.raises(FactorError):
        average_daily_value(panel, window=0)
    with pytest.raises(FactorError):
        liquidity_universe(panel, pd.DatetimeIndex([panel.index[0]]), top_n=0)
