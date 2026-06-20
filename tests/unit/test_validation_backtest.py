"""Tests for the event-driven, next-bar-open backtest core (P2.1, Deep Dive #2 §4b.6).

Scenarios are hand-computed: next-bar-open fills, end-of-session square-off (no overnight
MIS carry), the full Indian cost model, size/depth-aware slippage, and the latency
(execution-delay) knob — each isolated with zero/flat cost and slippage models.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant.core.config import load_config
from quant.core.frames import bars_to_frame
from quant.core.types import Bar, Side
from quant.data.store.errors import SchemaError
from quant.research.validation.backtest import (
    Backtester,
    _session_end_mask,
    create_backtester,
)
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.errors import BacktestError
from tests.unit.validation_fakes import (
    at,
    flat_slippage,
    session_bars,
    targets,
    zero_cost_model,
    zero_slippage,
)

D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)


def _frictionless(*, delay: int = 1, capital: float = 1_000_000.0) -> Backtester:
    """A backtester with no costs and no slippage (isolates fill/position mechanics)."""
    return Backtester(
        zero_cost_model(), zero_slippage(), initial_capital=capital, execution_delay_bars=delay
    )


def _net_shares(bt_result: object) -> int:
    """Signed shares traded across all fills (0 == ends flat, no overnight carry)."""
    fills = bt_result.fills  # type: ignore[attr-defined]
    return sum((f.quantity if f.side is Side.BUY else -f.quantity) for f in fills)


# --- session-boundary helper -------------------------------------------------


def test_session_end_mask_marks_each_session_boundary() -> None:
    # Two sessions (a,a,b): only the last bar of each session is flagged.
    sessions = np.array([D1, D1, D2], dtype="object")
    assert list(_session_end_mask(sessions)) == [False, True, True]


def test_session_end_mask_single_bar_is_a_boundary() -> None:
    assert list(_session_end_mask(np.array([D1], dtype="object"))) == [True]


def test_session_end_mask_empty_is_empty() -> None:
    assert _session_end_mask(np.array([], dtype="object")).tolist() == []


# --- next-bar-open + square-off ----------------------------------------------


def test_entry_fills_at_next_bar_open() -> None:
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10}))
    entry = result.fills[0]
    assert entry.timestamp == at(D1, 9, 30)  # decided at 09:15 close, filled at 09:30 open
    assert entry.side is Side.BUY
    assert entry.reference_price == 101.0
    assert entry.reason == "rebalance"


def test_position_is_squared_off_at_session_end() -> None:
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10}))
    exit_fill = result.fills[-1]
    assert exit_fill.timestamp == at(D1, 10, 0)  # the session's last bar
    assert exit_fill.side is Side.SELL
    assert exit_fill.reason == "square_off"
    assert _net_shares(result) == 0  # ends flat


def test_long_pnl_is_next_open_to_square_off_open() -> None:
    # Buy at the 09:30 open (101), squared off at the 10:00 open (103): +10 * (103-101).
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10}))
    assert result.net_pnl == pytest.approx(10 * (103 - 101))
    assert result.final_equity == pytest.approx(1_000_000 + 20)


def test_short_pnl_is_negative_when_price_rises() -> None:
    # Short 10 at the 09:30 open (110), cover at the 10:00 open (120): 10 * (110-120).
    bars = session_bars(D1, [100, 110, 115, 120])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): -10}))
    assert result.fills[0].side is Side.SELL  # opening the short
    assert result.fills[-1].side is Side.BUY  # covering at square-off
    assert result.fills[-1].reason == "square_off"
    assert result.net_pnl == pytest.approx(10 * (110 - 120))


# --- no overnight carry (MIS) ------------------------------------------------


def test_no_position_carries_across_sessions() -> None:
    # Session A trades; session B has no target. The square-off at A's end means B starts
    # flat and never trades — no decision bridges the overnight boundary.
    bars_a = session_bars(D1, [100, 101, 102])
    bars_b = session_bars(D2, [200, 201, 202])
    bars = pd.concat([bars_a, bars_b], ignore_index=True)
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10}))
    assert all(f.timestamp.date() == D1 for f in result.fills)  # all fills in session A
    assert _net_shares(result) == 0
    # Equity is flat across session B (no position held there).
    eq_b = result.equity_curve.loc[pd.DatetimeIndex([at(D2, 9, 15), at(D2, 9, 30), at(D2, 9, 45)])]
    assert eq_b.nunique() == 1


def test_decision_on_last_bar_does_not_carry_overnight() -> None:
    # A target set on session A's final decision bar cannot be acted on (square-off) and
    # must not open a position in session B.
    bars_a = session_bars(D1, [100, 101, 102])
    bars_b = session_bars(D2, [200, 201, 202])
    bars = pd.concat([bars_a, bars_b], ignore_index=True)
    result = _frictionless().run(bars, targets({at(D1, 9, 45): 10}))
    assert result.n_fills == 0
    assert result.net_pnl == pytest.approx(0.0)


# --- costs + slippage --------------------------------------------------------


def test_costs_reduce_net_pnl_by_exactly_the_modelled_cost() -> None:
    bars = session_bars(D1, [100, 110, 120])
    cost_model = IndianCostModel(load_config(environ={}).costs)
    bt = Backtester(cost_model, zero_slippage(), initial_capital=1_000_000)
    result = bt.run(bars, targets({at(D1, 9, 15): 100}))
    # Buy 100 @ 110 (next-bar-open), sell 100 @ 120 (square-off).
    buy = cost_model.cost_for_fill(Side.BUY, 110.0, 100)
    sell = cost_model.cost_for_fill(Side.SELL, 120.0, 100)
    gross = 100 * (120 - 110)
    assert result.total_costs == pytest.approx(buy.total + sell.total)
    assert result.net_pnl == pytest.approx(gross - (buy.total + sell.total))


def test_slippage_moves_fills_adversely() -> None:
    # Flat 10 bps: buy fills 0.1% above the open, sell 0.1% below.
    bars = session_bars(D1, [100, 110, 120])
    bt = Backtester(zero_cost_model(), flat_slippage(10.0), initial_capital=1_000_000)
    result = bt.run(bars, targets({at(D1, 9, 15): 100}))
    buy_price = 110.0 * (1 + 10.0 / 1e4)
    sell_price = 120.0 * (1 - 10.0 / 1e4)
    assert result.fills[0].fill_price == pytest.approx(buy_price)
    assert result.fills[1].fill_price == pytest.approx(sell_price)
    assert result.net_pnl == pytest.approx(100 * (sell_price - buy_price))


# --- latency (execution delay) -----------------------------------------------


def test_execution_delay_shifts_fill_further_out() -> None:
    # delay=2: a decision at 09:15 fills two bars later (09:45 open = 102), vs the next
    # bar (09:30) under delay=1.
    bars = session_bars(D1, [100, 101, 102, 103, 104])
    result = _frictionless(delay=2).run(bars, targets({at(D1, 9, 15): 10}))
    assert result.fills[0].timestamp == at(D1, 9, 45)
    assert result.fills[0].reference_price == 102.0
    assert result.net_pnl == pytest.approx(10 * (104 - 102))  # squared off at the 10:15 open


# --- target handling ---------------------------------------------------------


def test_targets_are_held_until_changed_within_session() -> None:
    # +10 then flip to -10 mid-session: buy 10, sell 20 (close long + open short), then
    # cover 10 at square-off. Round trips net to zero with no friction.
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10, at(D1, 9, 30): -10}))
    assert [(f.side, f.quantity) for f in result.fills] == [
        (Side.BUY, 10),
        (Side.SELL, 20),
        (Side.BUY, 10),
    ]
    assert result.net_pnl == pytest.approx(0.0)


def test_no_targets_means_no_trades() -> None:
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({}))
    assert result.n_fills == 0
    assert result.final_equity == pytest.approx(1_000_000)
    assert (result.equity_curve == 1_000_000).all()


# --- equity curve / returns --------------------------------------------------


def test_equity_curve_and_returns_shape() -> None:
    bars = session_bars(D1, [100, 101, 102, 103])
    result = _frictionless().run(bars, targets({at(D1, 9, 15): 10}))
    assert list(result.equity_curve.index) == list(pd.DatetimeIndex(bars["timestamp"]))
    assert pd.isna(result.returns.iloc[0])  # first bar has no prior to diff against
    assert result.equity_curve.iloc[0] == pytest.approx(1_000_000)  # starts flat at capital


def test_empty_bars_give_flat_empty_result() -> None:
    empty = bars_to_frame([])
    result = _frictionless().run(empty, targets({}))
    assert result.n_fills == 0
    assert result.final_equity == pytest.approx(1_000_000)
    assert result.equity_curve.empty


# --- factory -----------------------------------------------------------------


def test_create_backtester_wires_from_config() -> None:
    bt = create_backtester(load_config(environ={}))
    bars = session_bars(D1, [100, 110, 120])
    result = bt.run(bars, targets({at(D1, 9, 15): 100}))
    # Real cost + slippage from config -> net P&L below the frictionless gross of 1000.
    assert 0 < result.net_pnl < 100 * (120 - 110)
    assert result.total_costs > 0


# --- validation / fail-loud --------------------------------------------------


def test_multi_symbol_bars_rejected() -> None:
    bars = bars_to_frame(
        [
            Bar("X", at(D1, 9, 15), 100, 101, 99, 100, 10),
            Bar("Y", at(D1, 9, 15), 100, 101, 99, 100, 10),
        ]
    )
    with pytest.raises(BacktestError, match="one symbol"):
        _frictionless().run(bars, targets({}))


def test_duplicate_timestamps_rejected() -> None:
    bars = bars_to_frame(
        [
            Bar("X", at(D1, 9, 15), 100, 101, 99, 100, 10),
            Bar("X", at(D1, 9, 15), 100, 101, 99, 100, 10),
        ]
    )
    with pytest.raises(BacktestError, match="unique timestamps"):
        _frictionless().run(bars, targets({}))


def test_target_timestamp_without_a_bar_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102])
    bad = pd.Series([10], index=pd.DatetimeIndex([at(D1, 9, 20)]))  # 09:20 is not a bar
    with pytest.raises(BacktestError, match="no matching bar"):
        _frictionless().run(bars, bad)


def test_non_integer_target_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102])
    bad = pd.Series([10.5], index=pd.DatetimeIndex([at(D1, 9, 15)]))
    with pytest.raises(BacktestError, match="whole shares"):
        _frictionless().run(bars, bad)


def test_non_finite_target_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102])
    bad = pd.Series([np.nan], index=pd.DatetimeIndex([at(D1, 9, 15)]))
    with pytest.raises(BacktestError, match="finite"):
        _frictionless().run(bars, bad)


def test_non_datetime_target_index_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102])
    bad = pd.Series([10], index=[0])
    with pytest.raises(BacktestError, match="DatetimeIndex"):
        _frictionless().run(bars, bad)


def test_duplicate_target_index_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102])
    bad = pd.Series([10, 20], index=pd.DatetimeIndex([at(D1, 9, 15), at(D1, 9, 15)]))
    with pytest.raises(BacktestError, match="unique"):
        _frictionless().run(bars, bad)


def test_bad_schema_rejected() -> None:
    bars = session_bars(D1, [100, 101, 102]).drop(columns=["close"])
    with pytest.raises(SchemaError):
        _frictionless().run(bars, targets({}))


@pytest.mark.parametrize("capital", [0.0, -1.0])
def test_non_positive_initial_capital_rejected(capital: float) -> None:
    with pytest.raises(BacktestError, match="initial_capital"):
        Backtester(zero_cost_model(), zero_slippage(), initial_capital=capital)


def test_zero_execution_delay_rejected() -> None:
    with pytest.raises(BacktestError, match="execution_delay_bars"):
        Backtester(
            zero_cost_model(), zero_slippage(), initial_capital=1_000_000, execution_delay_bars=0
        )
