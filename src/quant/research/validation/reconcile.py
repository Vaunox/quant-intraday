"""Two-engine reconciliation (Deep Dive #2 §4b.7 — the implementation-risk check).

*"Run the same strategy through two engines … and reconcile — the same strategy can produce
materially different numbers in different engines, and that discrepancy is itself a source of
error you must quantify."* §4b.8 names VectorBT (vectorised) vs Backtrader/Nautilus
(event-driven) as the canonical fast-screen-vs-high-fidelity pair, but it equally sanctions
implementing the math directly (*"either way, understand the math, don't black-box it"*).

This module takes the second route — an **independent, fully vectorised reference engine**
(:class:`VectorizedBacktester`) reconciled against the P2.1 event-driven
:class:`~quant.research.validation.backtest.Backtester`. The choice is deliberate (and recorded
for the operator):

* The whole codebase hand-rolls over heavy dependencies (no sklearn/SciPy; hand-rolled PAVA,
  GMM, logistic) to keep the engine env lean (Part II Environment Policy). VectorBT pins
  numpy/numba and Backtrader is effectively unmaintained — both would contaminate the engine
  env or live research-only behind yet another adapter.
* The §4b.7 *purpose* is to quantify the discrepancy between two **independent implementations**
  of the same fill / cost / square-off semantics. A third-party engine knows nothing of the
  Indian cost model or our next-bar-open + intraday-square-off rules, so it could never
  reconcile *within tolerance* without re-implementing those semantics inside it anyway.

So the two engines share the *injected* cost and slippage **models** (separately tested) — what
differs is the **simulation structure**: the event-driven engine walks bar-by-bar with running
cash/position state; this engine derives the holdings path, the per-trade deltas, the cash flows
and the mark-to-market equity as **whole-array numpy operations** (no per-bar loop). If the two
agree to a tight tolerance on a sample strategy, the error-prone accounting (signed notional,
cost application, square-off timing, mark-to-market) is cross-validated; if they diverge, one
has a bug worth finding before any capital rides on it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.calendar import IST
from quant.core.config import Config
from quant.core.logging import get_logger
from quant.core.types import Side
from quant.data.store import serde
from quant.research.validation.backtest import BacktestResult, Fill
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.errors import BacktestError, ReconciliationError
from quant.research.validation.slippage import DepthAwareSlippage

_logger = get_logger(__name__)

#: Trade reasons recorded on a fill (mirrors the event-driven engine's vocabulary).
_REASON_REBALANCE = "rebalance"
_REASON_SQUARE_OFF = "square_off"


class BacktestEngine(Protocol):
    """A backtest engine: run a target-position path against bars and return the result."""

    def run(self, bars: pd.DataFrame, target_positions: pd.Series) -> BacktestResult:
        """Simulate ``target_positions`` against ``bars`` and return the :class:`BacktestResult`."""
        ...


class VectorizedBacktester:
    """A fully vectorised, independent reimplementation of the event-driven backtest core.

    Same contract as :class:`~quant.research.validation.backtest.Backtester` (next-bar-open
    fills, the injected Indian cost + size/depth slippage models, one IST date = one MIS session
    with a forced square-off at the session's last bar), computed as whole-array numpy operations
    rather than a per-bar loop. Built to be reconciled against the event-driven engine.
    """

    def __init__(
        self,
        cost_model: IndianCostModel,
        slippage_model: DepthAwareSlippage,
        *,
        initial_capital: float,
        execution_delay_bars: int = 1,
    ) -> None:
        """Build the engine (same knobs as the event-driven core).

        Raises:
            BacktestError: If ``initial_capital <= 0`` or ``execution_delay_bars < 1``.
        """
        if initial_capital <= 0:
            raise BacktestError(f"initial_capital must be positive, got {initial_capital!r}")
        if execution_delay_bars < 1:
            raise BacktestError(
                f"execution_delay_bars must be >= 1 (next-bar-open), got {execution_delay_bars!r}"
            )
        self._cost_model = cost_model
        self._slippage = slippage_model
        self._initial_capital = float(initial_capital)
        self._delay = execution_delay_bars

    def run(self, bars: pd.DataFrame, target_positions: pd.Series) -> BacktestResult:
        """Simulate ``target_positions`` against ``bars`` (vectorised); return the result.

        Raises:
            BacktestError: On multi-symbol bars, duplicate timestamps, or a mis-indexed /
                non-integer ``target_positions``.
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        if frame.empty:
            return self._empty_result()
        if frame["symbol"].nunique() > 1:
            raise BacktestError("the single-symbol backtest core requires one symbol per run")
        times = pd.DatetimeIndex(frame[serde.TIME_COLUMN])
        if not times.is_unique:
            raise BacktestError("bars must have unique timestamps (one bar per decision time)")

        session = np.asarray(times.tz_convert(IST).date, dtype="object")
        is_session_end = _session_end_mask(session)
        hold = self._holdings(times, session, is_session_end, target_positions)

        opens = frame["open"].to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")
        volumes = frame["volume"].to_numpy(dtype="float64")

        # Per-bar trade = change in held position; the position starts (and ends each session)
        # flat, so a leading/trailing trade is just the diff against zero.
        delta = np.diff(hold, prepend=0)
        fills, fill_price, cost = self._price_trades(times, delta, opens, volumes, is_session_end)

        # Cash walk as a single cumulative sum: a fill moves cash by -(price * delta) - cost
        # (a buy with delta>0 spends; a sell with delta<0 receives), then mark to market at close.
        cash_flow = -fill_price * delta - cost
        cash = self._initial_capital + np.cumsum(cash_flow)
        equity = cash + hold.astype("float64") * closes
        return self._build_result(times, equity, fills)

    def _holdings(
        self,
        times: pd.DatetimeIndex,
        session: npt.NDArray[np.object_],
        is_session_end: npt.NDArray[np.bool_],
        target_positions: pd.Series,
    ) -> npt.NDArray[np.int64]:
        """Return the signed position to hold during each bar (next-bar-open + square-off).

        Independent of the event-driven engine's index arithmetic: the sparse targets are
        forward-filled within each session, shifted forward by the execution delay (only
        inheriting a decision made in the *same* session), and forced flat on each session's
        last bar.
        """
        decided = self._scatter_targets(times, target_positions)
        session_series = pd.Series(session, index=np.arange(len(times)))
        decision = (
            pd.Series(decided).groupby(session_series, sort=False).ffill().fillna(0.0).to_numpy()
        )
        n = len(times)
        delay = self._delay
        shifted_decision = np.zeros(n, dtype="float64")
        shifted_session = np.full(n, None, dtype="object")
        if delay < n:
            shifted_decision[delay:] = decision[: n - delay]
            shifted_session[delay:] = session[: n - delay]
        same_session = session == shifted_session  # elementwise; leading None -> False
        hold = np.where(same_session, shifted_decision, 0.0).astype("int64")
        hold[is_session_end] = 0  # no overnight MIS position
        return hold

    def _scatter_targets(
        self, times: pd.DatetimeIndex, target_positions: pd.Series
    ) -> npt.NDArray[np.float64]:
        """Validate ``target_positions`` and scatter them onto the bar axis (NaN elsewhere)."""
        index = target_positions.index
        if not isinstance(index, pd.DatetimeIndex):
            raise BacktestError("target_positions must be indexed by bar timestamp (DatetimeIndex)")
        if not index.is_unique:
            raise BacktestError("target_positions index must be unique")
        unknown = index.difference(times)
        if len(unknown) > 0:
            raise BacktestError(
                f"target_positions has {len(unknown)} timestamp(s) with no matching bar"
            )
        values = target_positions.to_numpy(dtype="float64")
        if not np.all(np.isfinite(values)):
            raise BacktestError("target_positions must be finite (no NaN/inf share targets)")
        if not np.all(values == np.floor(values)):
            raise BacktestError("target_positions must be whole shares (integer positions)")
        decided = np.full(len(times), np.nan, dtype="float64")
        if len(index) > 0:
            decided[times.get_indexer(index)] = values
        return decided

    def _price_trades(
        self,
        times: pd.DatetimeIndex,
        delta: npt.NDArray[np.int64],
        opens: npt.NDArray[np.float64],
        volumes: npt.NDArray[np.float64],
        is_session_end: npt.NDArray[np.bool_],
    ) -> tuple[list[Fill], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Price + cost each non-zero trade; return the fills and the per-bar price/cost arrays."""
        n = len(times)
        fill_price = np.zeros(n, dtype="float64")
        cost_total = np.zeros(n, dtype="float64")
        fills: list[Fill] = []
        for raw in np.flatnonzero(delta):
            i = int(raw)
            change = int(delta[i])
            side = Side.BUY if change > 0 else Side.SELL
            quantity = abs(change)
            price = self._slippage.adjusted_fill_price(
                side, float(opens[i]), quantity, float(volumes[i])
            )
            breakdown = self._cost_model.cost_for_fill(side, price, quantity)
            fill_price[i] = price
            cost_total[i] = breakdown.total
            fills.append(
                Fill(
                    timestamp=times[i].to_pydatetime(),
                    side=side,
                    quantity=quantity,
                    reference_price=float(opens[i]),
                    fill_price=price,
                    cost=breakdown,
                    reason=_REASON_SQUARE_OFF if is_session_end[i] else _REASON_REBALANCE,
                )
            )
        return fills, fill_price, cost_total

    def _build_result(
        self,
        times: pd.DatetimeIndex,
        equity: npt.NDArray[np.float64],
        fills: Sequence[Fill],
    ) -> BacktestResult:
        """Assemble the equity curve, returns, and aggregates (matching the event-driven core)."""
        equity_curve = pd.Series(equity, index=times, name="equity")
        returns = equity_curve.pct_change(fill_method=None)
        returns.name = "returns"
        return BacktestResult(
            fills=tuple(fills),
            equity_curve=equity_curve,
            returns=returns,
            initial_capital=self._initial_capital,
            final_equity=float(equity[-1]),
            total_costs=float(sum(fill.cost.total for fill in fills)),
        )

    def _empty_result(self) -> BacktestResult:
        """The well-typed result for empty input: flat equity, no fills."""
        empty_index = pd.DatetimeIndex([], name=serde.TIME_COLUMN)
        return BacktestResult(
            fills=(),
            equity_curve=pd.Series(dtype="float64", index=empty_index, name="equity"),
            returns=pd.Series(dtype="float64", index=empty_index, name="returns"),
            initial_capital=self._initial_capital,
            final_equity=self._initial_capital,
            total_costs=0.0,
        )


def _session_end_mask(session: npt.NDArray[np.object_]) -> npt.NDArray[np.bool_]:
    """Boolean mask: ``True`` on the last bar of each session (where the next bar differs)."""
    if session.shape[0] == 0:
        return np.zeros(0, dtype=bool)
    return np.append(session[:-1] != session[1:], True)


def create_vectorized_backtester(config: Config) -> VectorizedBacktester:
    """Build a :class:`VectorizedBacktester` with the real cost/slippage models from ``config``.

    Wires the *same* :class:`IndianCostModel` / :class:`DepthAwareSlippage` and engine knobs as
    :func:`~quant.research.validation.backtest.create_backtester`, so the two engines differ only
    in their simulation structure — the property the reconciliation isolates.
    """
    return VectorizedBacktester(
        IndianCostModel(config.costs),
        DepthAwareSlippage(config.slippage),
        initial_capital=config.backtest.initial_capital_inr,
        execution_delay_bars=config.backtest.execution_delay_bars,
    )


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """The discrepancy between two engines on the same strategy (§4b.7 implementation-risk check).

    Every field is an absolute difference (or a count); ``reconciled`` is true only when each
    money difference is within ``tolerance`` and both engines produced the same number of fills.
    """

    n_bars: int
    primary_fills: int
    secondary_fills: int
    final_equity_diff: float
    net_pnl_diff: float
    total_costs_diff: float
    max_equity_curve_diff: float
    tolerance: float

    @property
    def fills_match(self) -> bool:
        """Whether both engines executed the same number of fills."""
        return self.primary_fills == self.secondary_fills

    @property
    def max_money_diff(self) -> float:
        """The largest of the money differences (the headline reconciliation gap)."""
        return max(
            self.final_equity_diff,
            self.net_pnl_diff,
            self.total_costs_diff,
            self.max_equity_curve_diff,
        )

    @property
    def reconciled(self) -> bool:
        """Whether the two engines agree within tolerance (and on the fill count)."""
        return self.fills_match and self.max_money_diff <= self.tolerance


def reconcile_engines(
    bars: pd.DataFrame,
    target_positions: pd.Series,
    *,
    primary: BacktestEngine,
    secondary: BacktestEngine,
    tolerance: float,
) -> ReconciliationReport:
    """Run one strategy through two engines and report whether they agree within ``tolerance``.

    Args:
        bars: The single symbol's canonical-schema bars.
        target_positions: The signed integer share targets (the sample strategy).
        primary: The reference engine (the P2.1 event-driven :class:`Backtester`).
        secondary: The second engine (the :class:`VectorizedBacktester`).
        tolerance: Maximum acceptable absolute money difference, INR (config; > 0).

    Raises:
        ReconciliationError: If ``tolerance <= 0`` or the two equity curves are indexed on
            different bars (so a per-bar difference is undefined).
    """
    if tolerance <= 0.0:
        raise ReconciliationError(f"tolerance must be positive, got {tolerance}")
    primary_result = primary.run(bars, target_positions)
    secondary_result = secondary.run(bars, target_positions)
    if not primary_result.equity_curve.index.equals(secondary_result.equity_curve.index):
        raise ReconciliationError("the two engines produced equity curves on different bars")

    if len(primary_result.equity_curve) == 0:
        max_curve_diff = 0.0
    else:
        max_curve_diff = float(
            np.max(np.abs(primary_result.equity_curve - secondary_result.equity_curve))
        )
    report = ReconciliationReport(
        n_bars=len(primary_result.equity_curve),
        primary_fills=primary_result.n_fills,
        secondary_fills=secondary_result.n_fills,
        final_equity_diff=abs(primary_result.final_equity - secondary_result.final_equity),
        net_pnl_diff=abs(primary_result.net_pnl - secondary_result.net_pnl),
        total_costs_diff=abs(primary_result.total_costs - secondary_result.total_costs),
        max_equity_curve_diff=max_curve_diff,
        tolerance=tolerance,
    )
    _logger.info(
        "engine reconciliation",
        extra={
            "reconciled": report.reconciled,
            "max_money_diff": report.max_money_diff,
            "primary_fills": report.primary_fills,
            "secondary_fills": report.secondary_fills,
        },
    )
    return report
