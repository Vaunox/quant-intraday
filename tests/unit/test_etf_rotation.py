"""Unit tests for the Step 4 cross-sectional rotation (pure pieces; the ensemble CV run is
exercised end-to-end by scripts/etf_rotation.py on real data)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quant.research.etf.benchmark import EquityCurve
from quant.research.etf.costs import ChargeSchedule, ETFCostModel, LegProfile
from quant.research.etf.rotation import (
    RotationConfig,
    backtest_weights,
    build_feature_rows,
    cross_sectional_labels,
    excess_returns,
    rotation_weights,
)


def _days(n: int) -> list[date]:
    return [date(2026, 1, 1) + timedelta(days=i) for i in range(n)]


def _free_model(symbols: list[str]) -> ETFCostModel:
    legs = {s: LegProfile(s, 0.0, 0.0, 0.0) for s in symbols}
    zero = ChargeSchedule(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return ETFCostModel(legs=legs, charges=zero)


def test_build_feature_rows_shapes_and_forward_label() -> None:
    cfg = RotationConfig(lookbacks=(2,), horizon=2, vol_window=3)
    dates = _days(10)
    prices = {"A": [float(10 + i) for i in range(10)]}  # strictly rising
    rows = build_feature_rows(dates, prices, cfg)
    # rows for t in [max_lookback=3, n-horizon=8) -> t=3..7
    assert [r.date for r in rows] == dates[3:8]
    sample = rows[0]
    assert set(sample.features) == {"mom_2", "vol_3", "ma_ratio"}
    # fwd_return at t=3: price[5]/price[3]-1
    assert sample.fwd_return == pytest.approx(prices["A"][5] / prices["A"][3] - 1.0)


def test_cross_sectional_labels_split_on_median() -> None:
    cfg = RotationConfig(lookbacks=(2,), horizon=2, vol_window=3)
    dates = _days(10)
    prices = {
        "WIN": [1.0 * (1.05**i) for i in range(10)],  # fastest riser
        "MID": [1.0 * (1.02**i) for i in range(10)],
        "LOSE": [1.0 * (0.99**i) for i in range(10)],
    }
    rows = build_feature_rows(dates, prices, cfg)
    labels = cross_sectional_labels(rows)
    day = rows[0].date
    assert labels[(day, "WIN")] == 1
    assert labels[(day, "LOSE")] == 0


def test_rotation_weights_pick_top_k_and_sum_to_one() -> None:
    cfg = RotationConfig(lookbacks=(2,), horizon=2, vol_window=3, top_k=2, use_regime_gate=False)
    dates = _days(40)
    prices = {
        "A": [10.0 + 0.1 * i for i in range(40)],
        "B": [10.0 + 0.2 * i for i in range(40)],
        "C": [10.0 + 0.05 * i for i in range(40)],
        "CASH": [1.0] * 40,
    }
    from quant.research.etf.benchmark import month_end_indices

    probs = {}
    for t in month_end_indices(dates):
        probs[(dates[t], "A")] = 0.9
        probs[(dates[t], "B")] = 0.8
        probs[(dates[t], "C")] = 0.1  # excluded by top_k=2
    sched = rotation_weights(dates, prices, probs, cfg, cash_symbol="CASH", market_symbol="A")
    some = next(iter(sched.values()))
    assert some["C"] == 0.0  # not chosen
    assert some["CASH"] == pytest.approx(0.0, abs=1e-9)  # fully invested (regime off)
    assert sum(some.values()) == pytest.approx(1.0)


def test_backtest_weights_flat_under_constant_prices_zero_cost() -> None:
    dates = _days(40)
    prices = {"A": [5.0] * 40, "CASH": [1.0] * 40}
    from quant.research.etf.benchmark import month_end_indices

    sched = {t: {"A": 1.0, "CASH": 0.0} for t in month_end_indices(dates)}
    curve = backtest_weights(dates, prices, sched, _free_model(["A", "CASH"]), capital=100_000.0)
    assert curve.equity[-1] == pytest.approx(100_000.0)


def test_excess_returns_subtracts_benchmark() -> None:
    strat = EquityCurve(_days(3), [100.0, 110.0, 121.0])  # +10%, +10%
    bench = EquityCurve(_days(3), [100.0, 105.0, 110.25])  # +5%, +5%
    assert excess_returns(strat, bench) == pytest.approx([0.05, 0.05])
