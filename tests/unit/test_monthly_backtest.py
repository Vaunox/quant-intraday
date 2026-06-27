"""Tests for the CNC cost model + monthly backtester (P3X.6) on synthetic books."""

import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.validation.errors import BacktestError
from quant.research.validation.monthly_backtest import (
    CncCostModel,
    monthly_backtest,
    reconcile_net_returns,
)

_IDX = pd.DatetimeIndex([pd.Timestamp("2020-01-31", tz=IST), pd.Timestamp("2020-02-28", tz=IST)])
_COLS = ["A", "B", "C"]


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=_IDX, columns=_COLS)


def test_cnc_round_trip_is_about_22_bps() -> None:
    model = CncCostModel()
    assert model.round_trip_rate() == pytest.approx(0.0022, abs=5e-5)
    # STT dominates and is charged on BOTH legs (the MIS model charges it sell-only).
    assert model.buy_leg_rate() > model.sell_leg_rate()  # buy carries stamp duty too


def test_monthly_backtest_gross_net_turnover() -> None:
    weights = _frame([[0.5, 0.5, 0.0], [0.0, 0.5, 0.5]])
    returns = _frame([[0.10, 0.0, 0.0], [0.0, 0.0, 0.20]])
    model = CncCostModel()
    result = monthly_backtest(weights, returns, cost_model=model, no_trade_band=0.0)
    assert result.gross_return.tolist() == pytest.approx([0.05, 0.10])
    assert result.turnover.tolist() == pytest.approx([1.0, 1.0])  # full establish, full rotate
    rate = model.round_trip_rate()
    assert result.net_return.tolist() == pytest.approx([0.05 - rate, 0.10 - rate])


def test_no_trade_band_suppresses_small_reweights() -> None:
    weights = _frame([[0.5, 0.5, 0.0], [0.48, 0.52, 0.0]])  # tiny drift at t1
    returns = _frame([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    model = CncCostModel()
    no_band = monthly_backtest(weights, returns, cost_model=model, no_trade_band=0.0)
    banded = monthly_backtest(weights, returns, cost_model=model, no_trade_band=0.25)
    assert no_band.turnover.iloc[1] == pytest.approx(0.04)  # 0.02 + 0.02 traded
    assert banded.turnover.iloc[1] == pytest.approx(0.0)  # below the band → not traded
    assert banded.cost.iloc[1] == pytest.approx(0.0)


def test_two_engines_reconcile_to_floating_point_noise() -> None:
    weights = _frame([[0.5, 0.5, 0.0], [0.0, 0.5, 0.5]])
    returns = _frame([[0.10, -0.02, 0.03], [0.01, 0.0, 0.20]])
    model = CncCostModel()
    for band in (0.0, 0.25):
        assert reconcile_net_returns(weights, returns, cost_model=model, no_trade_band=band) < 1e-12


def test_misaligned_frames_raise() -> None:
    weights = _frame([[0.5, 0.5, 0.0], [0.0, 0.5, 0.5]])
    bad = weights.rename(columns={"C": "D"})
    with pytest.raises(BacktestError):
        monthly_backtest(weights, bad, cost_model=CncCostModel())
