"""Unit tests for the Step 3 fixed-weight benchmark engine."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quant.research.etf.benchmark import (
    EquityCurve,
    buy_and_hold,
    equal_weight_rebalanced,
    month_end_indices,
    synthetic_cash_prices,
)
from quant.research.etf.costs import ChargeSchedule, ETFCostModel, LegProfile

_ZERO_CHARGES = ChargeSchedule(
    brokerage_per_order=0.0,
    exchange_txn_rate=0.0,
    sebi_rate=0.0,
    stamp_buy_rate=0.0,
    gst_rate=0.0,
    dp_charge_per_sell=0.0,
)


def _free_model(symbols: list[str]) -> ETFCostModel:
    """A cost model with all costs zeroed, for clean mechanical checks."""
    legs = {
        s: LegProfile(s, spread_bps=0.0, expense_ratio_annual=0.0, stt_sell_bps=0.0)
        for s in symbols
    }
    return ETFCostModel(legs=legs, charges=_ZERO_CHARGES)


def _days(n: int, start: date = date(2026, 1, 1)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def test_month_end_indices_marks_last_day_of_each_month() -> None:
    dates = [date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 2), date(2026, 2, 27)]
    assert month_end_indices(dates) == [1, 3]  # 31 Jan and the last Feb day present


def test_synthetic_cash_compounds_to_annual_yield() -> None:
    prices = synthetic_cash_prices(_days(253), annual_yield=0.06)
    # after 252 trading days the cash leg should be ~ +6%
    assert prices[252] / prices[0] == pytest.approx(1.06, rel=1e-6)


def test_equity_curve_metrics_on_known_path() -> None:
    curve = EquityCurve(dates=_days(3), equity=[100.0, 110.0, 99.0])
    assert curve.daily_returns() == pytest.approx([0.10, -0.10])
    assert curve.max_drawdown() == pytest.approx(99.0 / 110.0 - 1.0)


def test_free_constant_prices_give_flat_equity_at_capital() -> None:
    dates = _days(40)  # spans into February -> at least one rebalance
    prices = {"A": [1.0] * 40, "B": [1.0] * 40}
    curve = equal_weight_rebalanced(dates, prices, _free_model(["A", "B"]), capital=100_000.0)
    assert curve.equity[0] == pytest.approx(100_000.0)  # no entry cost
    assert curve.equity[-1] == pytest.approx(100_000.0)  # flat, rebalance is a no-op


def test_costs_reduce_equity_below_costless() -> None:
    dates = _days(40)
    prices = {"A": [1.0] * 40, "B": [1.0] * 40}
    costed = ETFCostModel(
        legs={
            s: LegProfile(s, spread_bps=10.0, expense_ratio_annual=0.0, stt_sell_bps=0.0)
            for s in "AB"
        }
    )
    curve = equal_weight_rebalanced(dates, prices, costed, capital=100_000.0)
    assert curve.equity[0] < 100_000.0  # entry costs paid at inception


def test_buy_and_hold_tracks_price_net_of_entry_cost() -> None:
    dates = _days(3)
    prices = [100.0, 110.0, 120.0]
    curve = buy_and_hold(dates, prices, "A", _free_model(["A"]), capital=100_000.0)
    assert curve.equity[0] == pytest.approx(100_000.0)
    assert curve.equity[-1] == pytest.approx(100_000.0 * 120.0 / 100.0)


def test_rebalance_captures_diversification_vs_drift() -> None:
    # A doubles then halves; B flat. Equal-weight rebalanced should not end below a pure
    # drift would on this mean-reverting path — sanity that rebalancing runs end to end.
    dates = _days(40)
    a = [1.0 + 0.02 * i for i in range(40)]
    prices = {"A": a, "B": [1.0] * 40}
    curve = equal_weight_rebalanced(dates, prices, _free_model(["A", "B"]), capital=100_000.0)
    assert len(curve.equity) == 40
    assert curve.equity[-1] > 100_000.0  # A trended up, basket gained
