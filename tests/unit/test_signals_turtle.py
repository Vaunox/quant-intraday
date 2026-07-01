"""Unit tests for the classic breakout Turtle signal (P3T.1).

Covers the pure primitives (Donchian levels, Wilder-N, the cash-capped sizer, the 2N stop)
and the causal trade state-machine (a known breakout, a known whipsaw stop-out, a
pyramided trend, and the S1 loser-filter), plus the two structural guarantees the spec
demands: forward-shift invariance (P1.8 leakage suite) and vectorized == incremental
(P1.7 dual-path). Small Donchian/ATR windows are used for the hand-built panels so the
mechanics are legible; the canonical 20/10/20 defaults drive the leakage/skew tests.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from quant.data.store import serde
from quant.research.signals import turtle
from quant.research.signals.errors import SignalInputError
from quant.research.signals.turtle import (
    DONCHIAN_EXIT,
    END,
    STOP,
    TurtleConfig,
    donchian_high,
    donchian_low,
    generate_trades,
    initial_stop,
    unit_size,
    wilder_atr,
)
from tests.adversarial import leakage

_IST = "Asia/Kolkata"


def _bars(
    ohlc: Sequence[tuple[float, float, float, float]], *, symbol: str = "TEST"
) -> pd.DataFrame:
    """Build a canonical-schema daily bars frame from ``(open, high, low, close)`` rows."""
    timestamps = pd.date_range("2024-01-01 09:15", periods=len(ohlc), freq="D", tz=_IST)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": timestamps,
            "open": [row[0] for row in ohlc],
            "high": [row[1] for row in ohlc],
            "low": [row[2] for row in ohlc],
            "close": [row[3] for row in ohlc],
            "volume": 1000,
        }
    )


def _random_walk(n: int, *, seed: int = 7) -> pd.DataFrame:
    """A deterministic random-walk OHLC panel for the structural (leakage/skew) tests."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    open_ = close + rng.normal(0, 0.3, n)
    return _bars(list(zip(open_, high, low, close, strict=True)))


# --- primitives --------------------------------------------------------------------------


def test_donchian_high_is_prior_window_extreme_excluding_current_bar() -> None:
    bars = _bars([(10, 11, 9, 10), (10, 12, 9, 11), (10, 10, 8, 9), (10, 13, 9, 12)])
    high = donchian_high(bars, 2)
    # First two rows NaN (need 2 prior bars + shift); row 2 = max(high[0], high[1]) = 12.
    assert np.isnan(high.iloc[0]) and np.isnan(high.iloc[1])
    assert high.iloc[2] == 12.0  # excludes the current bar's own high (10)
    assert high.iloc[3] == 12.0  # max(high[1], high[2]) = max(12, 10)


def test_donchian_low_is_prior_window_min() -> None:
    bars = _bars([(10, 11, 9, 10), (10, 12, 7, 11), (10, 10, 8, 9), (10, 13, 9, 12)])
    low = donchian_low(bars, 2)
    assert low.iloc[2] == 7.0  # min(low[0]=9, low[1]=7)
    assert low.iloc[3] == 7.0  # min(low[1]=7, low[2]=8)


def test_wilder_atr_matches_manual_recursion_and_differs_from_sma() -> None:
    # Constant true range → Wilder N equals that TR; then inject one spike and check the
    # recursion N_t = ((w-1)·N_{t-1} + TR_t)/w.
    bars = _bars([(10, 11, 9, 10)] * 5 + [(10, 15, 9, 14)] + [(10, 11, 9, 10)] * 3)
    n = wilder_atr(bars, 3)
    assert np.isnan(n.iloc[2])  # warm-up (first `window` rows NaN)
    assert n.iloc[3] == pytest.approx(2.0)  # seed = mean(TR[1..3]); TR is a constant 2.0
    # Row 5 has TR = max(15-9, |15-10|, |9-10|) = 6; N_5 = (2·2 + 6)/3 = 10/3.
    assert n.iloc[5] == pytest.approx((2 * 2.0 + 6.0) / 3.0)
    # Distinct from the SMA-ATR variant (they coincide *on* the spike bar; diverge after it,
    # where Wilder still carries the spike's memory and the SMA has rolled it partly off).
    from quant.data.features.volatility import atr as sma_atr

    assert n.iloc[6] != pytest.approx(sma_atr(bars, 3).iloc[6])


def test_unit_size_binds_on_cash_at_retail_scale() -> None:
    # ₹40k, N=5, price ₹2000: vol unit wants 80 shares but only 20 are affordable → cash binds.
    sized = unit_size(equity=40_000, atr_n=5.0, price=2_000.0, cash_available=40_000)
    assert sized.shares == 20
    assert sized.cash_bound is True
    assert sized.vol_unit_shares == pytest.approx(80.0)
    assert sized.affordable_shares == pytest.approx(20.0)


def test_unit_size_binds_on_volatility_when_cash_is_ample() -> None:
    sized = unit_size(equity=40_000, atr_n=5.0, price=100.0, cash_available=40_000)
    assert sized.shares == 80  # vol unit (80) < affordable (400)
    assert sized.cash_bound is False


def test_unit_size_zero_shares_when_one_share_is_unaffordable() -> None:
    sized = unit_size(equity=40_000, atr_n=5.0, price=50_000.0, cash_available=40_000)
    assert sized.shares == 0  # cannot afford a single share


def test_unit_size_rejects_bad_inputs() -> None:
    with pytest.raises(SignalInputError):
        unit_size(equity=0, atr_n=5.0, price=100.0, cash_available=1000)
    with pytest.raises(SignalInputError):
        unit_size(equity=40_000, atr_n=0.0, price=100.0, cash_available=1000)
    with pytest.raises(SignalInputError):
        unit_size(equity=40_000, atr_n=5.0, price=0.0, cash_available=1000)
    with pytest.raises(SignalInputError):
        unit_size(equity=40_000, atr_n=5.0, price=100.0, cash_available=-1.0)


def test_initial_stop_is_two_n_adverse() -> None:
    assert initial_stop(entry_price=100.0, atr_n=5.0, direction=1) == 90.0  # long: entry - 2N
    assert initial_stop(entry_price=100.0, atr_n=5.0, direction=-1) == 110.0  # short: entry + 2N


def test_turtle_config_validates_and_has_canonical_systems() -> None:
    s1, s2 = TurtleConfig.system1(), TurtleConfig.system2()
    assert (s1.entry_window, s1.exit_window, s1.use_loser_filter) == (20, 10, True)
    assert (s2.entry_window, s2.exit_window, s2.use_loser_filter) == (55, 20, False)
    with pytest.raises(SignalInputError):
        TurtleConfig(atr_window=1)


# --- trade generation --------------------------------------------------------------------

# A clean long breakout that trends up and exits on the opposite 2-bar low, in profit.
_WINNER_PANEL = _bars(
    [
        (10.0, 10.5, 9.5, 10.0),  # 0  warm-up range
        (10.0, 10.5, 9.5, 10.0),  # 1
        (10.0, 10.5, 9.5, 10.0),  # 2
        (10.5, 11.0, 10.4, 10.9),  # 3  breakout up → long entry at prior-3 high = 10.5
        (10.9, 11.2, 10.8, 11.1),  # 4  trend up; lows climb above entry
        (11.1, 11.6, 11.2, 11.5),  # 5
        (11.5, 11.6, 10.7, 10.8),  # 6  low breaks prior-2 low (10.8) → exit in profit
        (10.8, 10.9, 10.5, 10.6),  # 7  (post-exit)
    ]
)


def _small(
    *, exit_window: int = 2, use_loser_filter: bool = True, allow_short: bool = True
) -> TurtleConfig:
    """A canonical-mechanics config with small windows for the hand-built panels."""
    return TurtleConfig(
        entry_window=3,
        exit_window=exit_window,
        atr_window=3,
        use_loser_filter=use_loser_filter,
        allow_short=allow_short,
    )


def test_generate_trades_known_breakout_produces_one_winning_long() -> None:
    cfg = _small(use_loser_filter=False, allow_short=False)
    result = generate_trades(_WINNER_PANEL, cfg, equity=100_000, cash=100_000)

    assert len(result) == 1
    trade = result.trades.iloc[0]
    assert trade[turtle.DIRECTION] == 1
    assert trade[turtle.EXIT_REASON] == DONCHIAN_EXIT
    assert trade[turtle.ENTRY_PRICE] == pytest.approx(10.5)  # entered at the breakout level
    assert trade[turtle.EXIT_PRICE] == pytest.approx(10.8)  # exited at the opposite 2-bar low
    assert trade[turtle.RET] > 0
    assert trade[turtle.SHARES] == 1000  # (0.01·100k)/N=1.0

    # Position path: long from the entry bar's decision, flat again at the exit decision.
    pos = result.positions.to_numpy()
    assert list(pos[3:6]) == [1000, 1000, 1000]
    assert pos[6] == 0 and pos[0] == 0
    # label_times maps entry → exit for CPCV.
    assert result.label_times.iloc[0] == _WINNER_PANEL["timestamp"].iloc[6]


def test_generate_trades_whipsaw_hits_the_2n_stop_at_a_loss() -> None:
    panel = _bars(
        [
            (10.0, 10.5, 9.5, 10.0),  # 0 warm-up
            (10.0, 10.5, 9.5, 10.0),  # 1
            (10.0, 10.5, 9.5, 10.0),  # 2
            (10.5, 10.6, 10.4, 10.5),  # 3 marginal breakout → long entry at 10.5
            (10.5, 10.5, 8.4, 8.5),  # 4 collapses through the 2N stop
            (8.5, 8.6, 8.3, 8.4),  # 5
        ]
    )
    cfg = _small(use_loser_filter=False, allow_short=False)
    result = generate_trades(panel, cfg, equity=100_000, cash=100_000)

    assert len(result) == 1
    trade = result.trades.iloc[0]
    assert trade[turtle.EXIT_REASON] == STOP  # the stop, not the Donchian exit, fired first
    assert trade[turtle.RET] < 0
    assert result.positions.to_numpy()[4] == 0  # flat once stopped


def test_s1_loser_filter_suppresses_the_breakout_after_a_winner() -> None:
    # trade 1 (long) resolves a winner; a second (short) breakout immediately follows.
    panel = _bars(
        [
            (10.0, 10.5, 9.5, 10.0),  # 0 warm-up
            (10.0, 10.5, 9.5, 10.0),  # 1
            (10.0, 10.5, 9.5, 10.0),  # 2
            (10.5, 11.0, 10.4, 10.9),  # 3 long breakout, entry 10.5
            (10.9, 11.2, 10.8, 11.1),  # 4 lows climb above entry
            (11.1, 11.6, 11.2, 11.5),  # 5
            (11.5, 11.6, 10.7, 10.8),  # 6 exit long in profit (winner)
            (10.8, 10.9, 10.5, 10.6),  # 7 low ≤ prior-3 low → short breakout here
            (10.6, 10.7, 10.3, 10.4),  # 8
            (10.4, 10.5, 10.1, 10.2),  # 9
        ]
    )
    on = generate_trades(panel, _small(use_loser_filter=True), equity=100_000, cash=100_000)
    off = generate_trades(panel, _small(use_loser_filter=False), equity=100_000, cash=100_000)

    # With the filter OFF both breakouts are taken; with it ON the post-winner one is skipped.
    assert list(off.trades[turtle.DIRECTION]) == [1, -1]
    assert len(on) == 1
    assert on.trades.iloc[0][turtle.DIRECTION] == 1


def test_pyramiding_adds_units_on_a_sustained_trend() -> None:
    panel = _bars(
        [
            (10.0, 10.5, 9.5, 10.0),  # 0 warm-up (N seeds to 1.0)
            (10.0, 10.5, 9.5, 10.0),  # 1
            (10.0, 10.5, 9.5, 10.0),  # 2
            (10.5, 11.0, 10.4, 10.9),  # 3 entry 10.5; adds at +0.5N steps (11.0, 11.5)
            (10.9, 11.2, 10.9, 11.1),  # 4 high 11.2 ≥ 11.0 → add unit 2
            (11.1, 11.7, 11.3, 11.6),  # 5 high 11.7 ≥ 11.5 → add unit 3 (max)
            (11.6, 11.9, 11.6, 11.8),  # 6 hold
            (11.8, 12.0, 11.8, 11.9),  # 7 hold → marks out at END
        ]
    )
    cfg = TurtleConfig(
        entry_window=3,
        exit_window=10,
        atr_window=3,
        pyramiding=True,
        max_units=3,
        use_loser_filter=False,
    )
    result = generate_trades(panel, cfg, equity=100_000, cash=100_000)

    assert len(result) == 1
    trade = result.trades.iloc[0]
    assert trade[turtle.UNITS] == 3
    assert trade[turtle.SHARES] == 3000  # three 1000-share units ((0.01·100k)/N=1.0)
    assert trade[turtle.EXIT_REASON] == END
    assert result.positions.to_numpy().max() == 3000  # size stepped up to the full book


def test_pyramiding_degrades_gracefully_when_cash_is_exhausted() -> None:
    # ₹40k cash at a ~₹2000 price with N≈13.7: the first (already cash-capped) unit drains
    # the cash, so no pyramid unit can be added even though the trend keeps running.
    panel = _bars(
        [
            (2000.0, 2006.5, 1993.5, 2000.0),  # 0 warm-up (TR = 13)
            (2000.0, 2006.5, 1993.5, 2000.0),  # 1
            (2000.0, 2006.5, 1993.5, 2000.0),  # 2
            (2006.5, 2015.0, 2005.0, 2014.0),  # 3 breakout → entry at 2006.5
            (2014.0, 2060.0, 2013.0, 2055.0),  # 4 favorable, but no cash to add
            (2055.0, 2100.0, 2054.0, 2095.0),  # 5
        ]
    )
    cfg = TurtleConfig(
        entry_window=3,
        exit_window=10,
        atr_window=3,
        pyramiding=True,
        max_units=4,
        use_loser_filter=False,
    )
    result = generate_trades(panel, cfg, equity=40_000, cash=40_000)
    trade = result.trades.iloc[0]
    assert trade[turtle.UNITS] == 1  # could not afford a second unit
    assert bool(trade[turtle.CASH_BOUND]) is True


def test_generate_trades_empty_bars_returns_empty() -> None:
    empty = serde.empty_bars_frame()
    result = generate_trades(empty, _small(), equity=100_000, cash=100_000)
    assert len(result) == 0
    assert result.positions.empty
    assert result.label_times.empty


def test_generate_trades_rejects_bad_capital() -> None:
    with pytest.raises(SignalInputError):
        generate_trades(_WINNER_PANEL, _small(), equity=0, cash=100)
    with pytest.raises(SignalInputError):
        generate_trades(_WINNER_PANEL, _small(), equity=100, cash=-1)


# --- structural guarantees (P1.8 leakage; P1.7 dual-path) --------------------------------


@pytest.mark.parametrize("fn", [donchian_high, donchian_low, wilder_atr])
def test_primitives_are_forward_shift_invariant(fn) -> None:  # type: ignore[no-untyped-def]
    bars = _random_walk(60)
    leakage.assert_no_lookahead(lambda frame: fn(frame, 20), bars, split=40)


def test_primitives_are_skew_free_on_the_dual_path() -> None:
    bars = _random_walk(60)

    def frame_fn(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "dhigh": donchian_high(frame, 20).to_numpy(),
                "dlow": donchian_low(frame, 20).to_numpy(),
                "n": wilder_atr(frame, 20).to_numpy(),
            },
            index=pd.DatetimeIndex(frame["timestamp"]),
        )

    def asof_fn(frame: pd.DataFrame, asof) -> pd.Series:  # type: ignore[no-untyped-def]
        history = frame[frame["timestamp"] <= asof]
        return frame_fn(history).iloc[-1]

    leakage.assert_skew_free(frame_fn, asof_fn, bars)


def test_generate_trades_vectorized_equals_incremental_on_resolved_region() -> None:
    # The signal is a strict left-to-right pass, so truncating the panel at a *flat* bar
    # (the trade has already exited by index 6) reproduces the resolved position path.
    cfg = _small(use_loser_filter=False)
    full = generate_trades(_WINNER_PANEL, cfg, equity=100_000, cash=100_000)
    prefix = generate_trades(_WINNER_PANEL.iloc[:7], cfg, equity=100_000, cash=100_000)
    pd.testing.assert_series_equal(full.positions.iloc[:7], prefix.positions)
