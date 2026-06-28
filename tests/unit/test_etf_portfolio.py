"""Unit tests for the vol-targeted risk-parity portfolio manager."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quant.research.etf.costs import ChargeSchedule, ETFCostModel, LegProfile
from quant.research.etf.portfolio import (
    PMConfig,
    realized_vol,
    risk_parity_schedule,
    run_risk_parity_pm,
)


def _days(n: int) -> list[date]:
    return [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]


def _free_model(symbols: list[str]) -> ETFCostModel:
    legs = {s: LegProfile(s, 0.0, 0.0, 0.0) for s in symbols}
    return ETFCostModel(legs=legs, charges=ChargeSchedule(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))


def test_realized_vol_zero_for_constant_returns() -> None:
    assert realized_vol([1.0, 1.01, 1.0201, 1.030301], end=3, window=3) == pytest.approx(0.0)


def test_inverse_vol_gives_lower_weight_to_higher_vol_asset() -> None:
    cfg = PMConfig(vol_lookback=5, target_vol=10.0)  # huge target -> gross ~1, isolate weights
    dates = _days(40)
    calm = [10.0 * (1.001**i) for i in range(40)]  # low vol
    wild = [10.0 * (1.05 if i % 2 else 0.96) ** 1 for i in range(40)]  # high vol (oscillating)
    prices = {"CALM": calm, "WILD": wild, "CASH": [1.0] * 40}
    sched = risk_parity_schedule(dates, prices, cfg, cash_symbol="CASH")
    weights = next(iter(sched.values()))
    assert weights["CALM"] > weights["WILD"]  # risk parity downweights the volatile leg


def test_vol_target_moves_to_cash_when_portfolio_vol_exceeds_target() -> None:
    cfg = PMConfig(vol_lookback=5, target_vol=0.05)  # tiny target -> must de-risk
    dates = _days(40)
    wild = [10.0 * (1.06 if i % 2 else 0.95) ** 1 for i in range(40)]
    prices = {"WILD": wild, "CASH": [1.0] * 40}
    sched = risk_parity_schedule(dates, prices, cfg, cash_symbol="CASH")
    weights = next(iter(sched.values()))
    assert weights["CASH"] > 0.0  # gross scaled below 1 -> cash holds the residual
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["WILD"] <= 1.0  # never levered


def test_run_pm_constant_prices_flat_zero_cost() -> None:
    cfg = PMConfig(vol_lookback=5, target_vol=0.10)
    dates = _days(40)
    prices = {"A": [5.0] * 40, "B": [5.0] * 40, "CASH": [1.0] * 40}
    curve = run_risk_parity_pm(
        dates, prices, _free_model(["A", "B", "CASH"]), cfg, cash_symbol="CASH"
    )
    # constant prices -> zero realized vol -> gross capped at 1; equity stays at capital
    assert curve.equity[-1] == pytest.approx(100_000.0)
