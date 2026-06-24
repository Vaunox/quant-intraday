"""Tests for the two-engine reconciliation (P2.8, Deep Dive #2 §4b.7 implementation-risk check).

The headline acceptance criterion — *"two engines reconcile within tolerance on a sample
strategy"* — is pinned by running a non-trivial strategy through both the event-driven P2.1
:class:`Backtester` and the independent vectorised :class:`VectorizedBacktester` and asserting
they agree to floating-point noise (equity curve, net P&L, costs, fill count). The rest pin the
vectorised engine's edge cases (next-bar delay, session square-off, validation) and the
reconciliation report's pass/fail logic, including a deliberately divergent fake engine.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.core.config import Config, load_config
from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.research.validation.backtest import BacktestResult, create_backtester
from quant.research.validation.errors import BacktestError, ReconciliationError
from quant.research.validation.reconcile import (
    ReconciliationReport,
    VectorizedBacktester,
    _session_end_mask,
    create_vectorized_backtester,
    reconcile_engines,
)

IST = ZoneInfo("Asia/Kolkata")
REPO_CONFIG = "config"


def _config() -> Config:
    return load_config(env="dev", environ={"QUANT_CONFIG_DIR": REPO_CONFIG})


def _bars(sessions: int, *, bars_per_session: int = 8, seed: int = 0) -> pd.DataFrame:
    """Weekday sessions of 15-minute bars from a gentle random walk (one symbol)."""
    rng = np.random.default_rng(seed)
    rows: list[Bar] = []
    price = 100.0
    day = datetime(2024, 1, 1, tzinfo=IST)
    placed = 0
    while placed < sessions:
        if day.weekday() < 5:
            ts = datetime.combine(day.date(), time(9, 15), tzinfo=IST)
            for _ in range(bars_per_session):
                nxt = price * (1.0 + float(rng.normal(0.0, 0.002)))
                high = max(price, nxt) * 1.001
                low = min(price, nxt) * 0.999
                rows.append(Bar("AAA", ts, price, high, low, nxt, int(rng.integers(2000, 8000))))
                price = nxt
                ts += timedelta(minutes=15)
            placed += 1
        day += timedelta(days=1)
    return bars_to_frame(rows)


def _random_targets(bars: pd.DataFrame, *, seed: int) -> pd.Series:
    """A random integer target path on a subset of the bars (the sample strategy)."""
    rng = np.random.default_rng(seed)
    times = pd.DatetimeIndex(bars["timestamp"])
    chosen = sorted(rng.choice(len(times), size=len(times) // 2, replace=False))
    values = rng.integers(-200, 200, size=len(chosen))
    return pd.Series(values.astype("int64"), index=times[chosen])


# --------------------------------------------------------------------------------------------
# The headline: the two engines reconcile on a sample strategy
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_two_engines_reconcile_within_tolerance(seed: int) -> None:
    config = _config()
    bars = _bars(sessions=6, seed=seed)
    targets = _random_targets(bars, seed=seed + 100)
    report = reconcile_engines(
        bars,
        targets,
        primary=create_backtester(config),
        secondary=create_vectorized_backtester(config),
        tolerance=1e-6,
    )
    assert report.reconciled
    assert report.fills_match
    assert report.max_money_diff < 1e-6


def test_engines_produce_identical_equity_curves() -> None:
    config = _config()
    bars = _bars(sessions=8, seed=42)
    targets = _random_targets(bars, seed=7)
    primary = create_backtester(config).run(bars, targets)
    secondary = create_vectorized_backtester(config).run(bars, targets)
    pd.testing.assert_series_equal(
        primary.equity_curve, secondary.equity_curve, check_exact=False, atol=1e-6
    )
    assert primary.n_fills == secondary.n_fills
    assert primary.total_costs == pytest.approx(secondary.total_costs)


# --------------------------------------------------------------------------------------------
# VectorizedBacktester semantics
# --------------------------------------------------------------------------------------------


def test_vectorized_squares_off_at_session_end() -> None:
    config = _config()
    bars = _bars(sessions=2, bars_per_session=6, seed=1)
    times = pd.DatetimeIndex(bars["timestamp"])
    # Go long at the second bar of session 1; never explicitly flatten.
    targets = pd.Series([100], index=[times[1]])
    result = create_vectorized_backtester(config).run(bars, targets)
    # The position is squared off by the last bar of each session -> ends flat (no overnight).
    assert result.equity_curve.iloc[5] == pytest.approx(result.equity_curve.iloc[-1], rel=1e-6)
    # Two fills: the entry (next bar open) and the square-off.
    assert result.n_fills == 2
    assert any(fill.reason == "square_off" for fill in result.fills)


def test_vectorized_handles_one_bar_with_delay() -> None:
    # A single bar: the next-bar decision can never fill (delay >= n branch) -> flat, no fills.
    config = _config()
    bars = _bars(sessions=1, bars_per_session=1, seed=1)
    times = pd.DatetimeIndex(bars["timestamp"])
    targets = pd.Series([50], index=[times[0]])
    result = create_vectorized_backtester(config).run(bars, targets)
    assert result.n_fills == 0
    assert result.final_equity == pytest.approx(config.backtest.initial_capital_inr)


def test_vectorized_empty_bars_is_flat() -> None:
    config = _config()
    result = create_vectorized_backtester(config).run(bars_to_frame([]), pd.Series(dtype="int64"))
    assert result.n_fills == 0
    assert result.final_equity == config.backtest.initial_capital_inr
    assert result.equity_curve.empty


def test_vectorized_rejects_multi_symbol_and_duplicate_timestamps() -> None:
    config = _config()
    engine = create_vectorized_backtester(config)
    multi = bars_to_frame(
        [
            Bar("AAA", datetime(2024, 1, 1, 9, 15, tzinfo=IST), 100, 101, 99, 100, 100),
            Bar("BBB", datetime(2024, 1, 1, 9, 30, tzinfo=IST), 100, 101, 99, 100, 100),
        ]
    )
    with pytest.raises(BacktestError, match="one symbol per run"):
        engine.run(multi, pd.Series(dtype="int64"))
    ts = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    dup = bars_to_frame(
        [Bar("AAA", ts, 100, 101, 99, 100, 100), Bar("AAA", ts, 100, 101, 99, 100, 100)]
    )
    with pytest.raises(BacktestError, match="unique timestamps"):
        engine.run(dup, pd.Series(dtype="int64"))


def test_vectorized_rejects_bad_target_positions() -> None:
    config = _config()
    engine = create_vectorized_backtester(config)
    bars = _bars(sessions=1, seed=1)
    times = pd.DatetimeIndex(bars["timestamp"])
    with pytest.raises(BacktestError, match="DatetimeIndex"):
        engine.run(bars, pd.Series([1], index=[0]))
    with pytest.raises(BacktestError, match="unique"):
        engine.run(bars, pd.Series([1, 2], index=[times[0], times[0]]))
    with pytest.raises(BacktestError, match="no matching bar"):
        engine.run(bars, pd.Series([1], index=[datetime(2030, 1, 1, tzinfo=IST)]))
    with pytest.raises(BacktestError, match="finite"):
        engine.run(bars, pd.Series([np.nan], index=[times[0]]))
    with pytest.raises(BacktestError, match="whole shares"):
        engine.run(bars, pd.Series([1.5], index=[times[0]]))


def test_vectorized_constructor_validates() -> None:
    config = _config()
    from quant.research.validation.costs import IndianCostModel
    from quant.research.validation.slippage import DepthAwareSlippage

    cost = IndianCostModel(config.costs)
    slip = DepthAwareSlippage(config.slippage)
    with pytest.raises(BacktestError, match="initial_capital"):
        VectorizedBacktester(cost, slip, initial_capital=0.0)
    with pytest.raises(BacktestError, match="next-bar-open"):
        VectorizedBacktester(cost, slip, initial_capital=1e6, execution_delay_bars=0)


def test_session_end_mask_empty() -> None:
    assert _session_end_mask(np.array([], dtype="object")).shape == (0,)


# --------------------------------------------------------------------------------------------
# ReconciliationReport + reconcile_engines
# --------------------------------------------------------------------------------------------


def test_reconcile_engines_empty_bars_trivially_reconciles() -> None:
    config = _config()
    report = reconcile_engines(
        bars_to_frame([]),
        pd.Series(dtype="int64"),
        primary=create_backtester(config),
        secondary=create_vectorized_backtester(config),
        tolerance=1e-6,
    )
    assert report.reconciled
    assert report.n_bars == 0
    assert report.max_equity_curve_diff == 0.0


def test_reconcile_engines_rejects_non_positive_tolerance() -> None:
    config = _config()
    with pytest.raises(ReconciliationError, match="tolerance must be positive"):
        reconcile_engines(
            _bars(sessions=1, seed=1),
            pd.Series(dtype="int64"),
            primary=create_backtester(config),
            secondary=create_vectorized_backtester(config),
            tolerance=0.0,
        )


def test_reconcile_engines_flags_divergent_indices() -> None:
    config = _config()
    bars = _bars(sessions=1, seed=1)

    class _MisalignedEngine:
        """A fake engine whose equity curve is indexed on different bars."""

        def run(self, _bars: pd.DataFrame, _targets: pd.Series) -> BacktestResult:
            idx = pd.DatetimeIndex([datetime(2099, 1, 1, tzinfo=IST)], name="timestamp")
            empty = pd.Series([1.0], index=idx)
            return BacktestResult(
                fills=(),
                equity_curve=empty,
                returns=empty,
                initial_capital=1e6,
                final_equity=1.0,
                total_costs=0.0,
            )

    empty_targets = pd.Series(
        dtype="int64", index=pd.DatetimeIndex([], name="timestamp")
    )  # valid (DatetimeIndex) so the real primary engine accepts it
    with pytest.raises(ReconciliationError, match="different bars"):
        reconcile_engines(
            bars,
            empty_targets,
            primary=create_backtester(config),
            secondary=_MisalignedEngine(),
            tolerance=1e-6,
        )


def test_reconciliation_report_fields() -> None:
    report = ReconciliationReport(
        n_bars=10,
        primary_fills=3,
        secondary_fills=3,
        final_equity_diff=0.0,
        net_pnl_diff=0.0,
        total_costs_diff=0.0,
        max_equity_curve_diff=5e-7,
        tolerance=1e-6,
    )
    assert report.fills_match
    assert report.max_money_diff == pytest.approx(5e-7)
    assert report.reconciled


def test_reconciliation_report_flags_a_mismatch() -> None:
    report = ReconciliationReport(
        n_bars=10,
        primary_fills=3,
        secondary_fills=4,  # fill counts disagree
        final_equity_diff=100.0,
        net_pnl_diff=100.0,
        total_costs_diff=2.0,
        max_equity_curve_diff=50.0,
        tolerance=1e-6,
    )
    assert not report.fills_match
    assert not report.reconciled
