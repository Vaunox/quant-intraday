"""The realistic, event-driven backtest core (Deep Dive #2 §4b.6).

*"The simulation must model reality or the P&L is fantasy."* This is where most "edges"
die. The core simulates a single symbol's intraday MIS trading with the four
non-negotiables of §4b.6:

* **Next-bar-open execution.** A target decided on bar *t*'s close fills at bar
  *t+delay*'s **open** — never the close it was decided on. ``delay`` defaults to 1 (the
  canonical next-bar rule), the *same* rule in research and live (Inviolable Rule 2).
* **Full Indian cost model** (:class:`~quant.research.validation.costs.IndianCostModel`) —
  every fill pays itemised, per-order brokerage/STT/exchange/SEBI/stamp/GST.
* **Size/depth-aware slippage**
  (:class:`~quant.research.validation.slippage.DepthAwareSlippage`) — the open is moved
  adversely by the order's size vs the bar's liquidity.
* **Latency** — modelled as ``execution_delay_bars``; at the 15-min decision clock a
  sub-bar latency cannot change *which* bar you fill at, so the realistic delay is
  expressed in whole bars (≥ 1).

**Intraday discipline (MIS).** One IST date = one session (the vertical/square-off
barrier). The engine therefore (a) never fills a decision across a session boundary —
each session starts flat — and (b) **squares off at the open of each session's last
bar**, so no position is ever carried overnight. Squaring off at the final bar's open
(≈ 15:15 on a 15-min clock) lines up with the configured self-square-off
(``execution.self_square_off_time``).

**Inputs.** ``bars`` is a single symbol's canonical-schema, hygiene-clean, *adjusted*
bars (one row per decision-clock bar). ``target_positions`` is a Series indexed by bar
timestamp whose values are the **signed integer share** position the strategy wants to
hold from that bar's decision onward (positive long, negative short, 0 flat). Bars
without an explicit target hold the session's most recent target (0 at session start).
The capital/sizing layer (P3.4) produces these targets; the backtester only executes
them — faithfully, net of costs.

**Output.** A :class:`BacktestResult`: the per-fill log, the mark-to-market equity curve
and its per-bar returns (the input the CPCV path-Sharpe and walk-forward of P2.2 consume),
and headline net-P&L / cost aggregates.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.calendar import IST
from quant.core.config import Config
from quant.core.logging import get_logger
from quant.core.types import Side
from quant.data.store import serde
from quant.research.validation.costs import CostBreakdown, IndianCostModel
from quant.research.validation.errors import BacktestError
from quant.research.validation.slippage import DepthAwareSlippage

_logger = get_logger(__name__)

#: Trade reasons recorded on a fill.
_REASON_REBALANCE = "rebalance"
_REASON_SQUARE_OFF = "square_off"


@dataclass(frozen=True, slots=True)
class Fill:
    """A single executed order produced by the backtest.

    ``reference_price`` is the bar open before slippage; ``fill_price`` is what was paid
    after adverse slippage; ``cost`` is the itemised Indian transaction cost. ``reason``
    distinguishes a strategy ``rebalance`` from a forced end-of-session ``square_off``.
    """

    timestamp: datetime  # the fill bar's timestamp (tz-aware IST)
    side: Side
    quantity: int  # absolute shares filled (> 0)
    reference_price: float  # bar open, pre-slippage
    fill_price: float  # post-slippage execution price
    cost: CostBreakdown
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """The outcome of a backtest run.

    ``equity_curve`` is mark-to-market equity at each bar's close (indexed by bar
    timestamp); ``returns`` is its per-bar simple return (first bar ``NaN``). These are
    the inputs the CPCV path-Sharpe / walk-forward (P2.2) consume. The aggregates are
    net of all costs.
    """

    fills: tuple[Fill, ...]
    equity_curve: pd.Series
    returns: pd.Series
    initial_capital: float
    final_equity: float
    total_costs: float

    @property
    def net_pnl(self) -> float:
        """Net profit/loss over the run (final equity - starting capital), after costs."""
        return self.final_equity - self.initial_capital

    @property
    def n_fills(self) -> int:
        """Number of executed orders."""
        return len(self.fills)


class Backtester:
    """Event-driven, next-bar-open backtest engine for a single symbol (MIS, intraday).

    Construct with an injected cost model and slippage model (Ground Rule 1) plus the
    engine knobs; :meth:`run` executes a target-position path against bars. Use
    :func:`create_backtester` to wire the real models from :class:`Config`.
    """

    def __init__(
        self,
        cost_model: IndianCostModel,
        slippage_model: DepthAwareSlippage,
        *,
        initial_capital: float,
        execution_delay_bars: int = 1,
    ) -> None:
        """Build the engine.

        Args:
            cost_model: The Indian transaction-cost model applied per fill.
            slippage_model: The size/depth-aware slippage model applied to each fill.
            initial_capital: Starting equity (INR, > 0) the run marks to market against.
            execution_delay_bars: Decision→fill delay in bars (>= 1). 1 = next-bar-open.

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
        """Simulate trading ``target_positions`` against ``bars`` and return the result.

        Args:
            bars: A single symbol's canonical-schema, hygiene-clean, adjusted bars.
            target_positions: Signed integer share targets indexed by bar timestamp (a
                subset of ``bars``' timestamps). Bars without a target hold the session's
                most recent one (0 at session start).

        Returns:
            The :class:`BacktestResult` (fills, equity curve, returns, net aggregates).

        Raises:
            BacktestError: If ``bars`` holds more than one symbol, has duplicate
                timestamps, or ``target_positions`` is mis-indexed / non-integer.
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

        session = self._session_ids(times)
        is_session_end = _session_end_mask(session)
        hold = self._holdings_path(times, session, is_session_end, target_positions)

        opens = frame["open"].to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")
        volumes = frame["volume"].to_numpy(dtype="float64")

        cash = self._initial_capital
        position = 0
        fills: list[Fill] = []
        equity = np.empty(len(frame), dtype="float64")
        for i in range(len(frame)):
            delta = int(hold[i]) - position
            if delta != 0:
                fill = self._execute(
                    timestamp=times[i].to_pydatetime(),
                    delta=delta,
                    reference_price=float(opens[i]),
                    liquidity=float(volumes[i]),
                    square_off=bool(is_session_end[i]),
                )
                # Cash out on a buy (pay notional + cost), in on a sell (receive notional
                # - cost). Mark-to-market uses the post-trade position at the bar close.
                notional = fill.fill_price * fill.quantity
                signed_notional = -notional if fill.side is Side.BUY else notional
                cash += signed_notional - fill.cost.total
                position = int(hold[i])
                fills.append(fill)
            equity[i] = cash + position * float(closes[i])

        return self._build_result(times, equity, fills)

    def _execute(
        self,
        *,
        timestamp: datetime,
        delta: int,
        reference_price: float,
        liquidity: float,
        square_off: bool,
    ) -> Fill:
        """Price and cost a single fill that moves the position by ``delta`` shares."""
        side = Side.BUY if delta > 0 else Side.SELL
        quantity = abs(delta)
        fill_price = self._slippage.adjusted_fill_price(side, reference_price, quantity, liquidity)
        cost = self._cost_model.cost_for_fill(side, fill_price, quantity)
        return Fill(
            timestamp=timestamp,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            fill_price=fill_price,
            cost=cost,
            reason=_REASON_SQUARE_OFF if square_off else _REASON_REBALANCE,
        )

    def _holdings_path(
        self,
        times: pd.DatetimeIndex,
        session: npt.NDArray[np.object_],
        session_end: npt.NDArray[np.bool_],
        target_positions: pd.Series,
    ) -> npt.NDArray[np.int64]:
        """Return ``hold[i]``: the signed position to hold *during* bar ``i``.

        ``hold[i]`` is the target decided ``delay`` bars earlier within the same session
        (0 if that decision is in a prior session or before the first ``delay`` bars), and
        is forced to 0 on each session's last bar (square-off). This is the only place the
        decision→fill delay and the no-overnight rule are applied, so the simulation loop
        stays a plain cash/position walk.
        """
        decision = self._decisions_per_bar(times, session, target_positions)
        n = len(times)
        positions = np.arange(n)
        source = positions - self._delay
        hold = np.zeros(n, dtype="int64")
        valid = source >= 0
        # Only inherit a decision when it was made in the *same* session as the fill bar.
        same_session = session[positions[valid]] == session[source[valid]]
        hold[positions[valid]] = np.where(same_session, decision[source[valid]], 0)
        # Square-off: flat on each session's last bar (no overnight MIS position).
        hold[session_end] = 0
        return hold

    def _decisions_per_bar(
        self,
        times: pd.DatetimeIndex,
        session: npt.NDArray[np.object_],
        target_positions: pd.Series,
    ) -> npt.NDArray[np.int64]:
        """Map targets onto every bar: the most recent in-session target (0 if none yet)."""
        decided = self._aligned_targets(times, target_positions)
        # Forward-fill the sparse decisions within each session, default 0 at session start.
        filled = (
            pd.Series(decided, name="d").groupby(pd.Index(session)).ffill().fillna(0.0).to_numpy()
        )
        return filled.astype("int64")

    def _aligned_targets(
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

    @staticmethod
    def _session_ids(times: pd.DatetimeIndex) -> npt.NDArray[np.object_]:
        """One id per bar = its IST calendar date (one IST date == one trading session)."""
        return np.asarray(times.tz_convert(IST).date, dtype="object")

    def _build_result(
        self,
        times: pd.DatetimeIndex,
        equity: npt.NDArray[np.float64],
        fills: Sequence[Fill],
    ) -> BacktestResult:
        """Assemble the equity curve, returns, and aggregates from the simulation."""
        equity_curve = pd.Series(equity, index=times, name="equity")
        # fill_method=None: equity has no gaps, and the pandas default is deprecated.
        returns = equity_curve.pct_change(fill_method=None)
        returns.name = "returns"
        total_costs = float(sum(fill.cost.total for fill in fills))
        final_equity = float(equity[-1])
        _logger.info(
            "backtest complete",
            extra={
                "bars": len(times),
                "fills": len(fills),
                "net_pnl": final_equity - self._initial_capital,
                "total_costs": total_costs,
            },
        )
        return BacktestResult(
            fills=tuple(fills),
            equity_curve=equity_curve,
            returns=returns,
            initial_capital=self._initial_capital,
            final_equity=final_equity,
            total_costs=total_costs,
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
    # A bar ends a session when the following bar is a different session; the final bar
    # always ends its session.
    return np.append(session[:-1] != session[1:], True)


def create_backtester(config: Config) -> Backtester:
    """Build a :class:`Backtester` with the real cost/slippage models from ``config``.

    Wires :class:`IndianCostModel` (``config.costs``) and :class:`DepthAwareSlippage`
    (``config.slippage``) and reads the engine knobs from ``config.backtest`` — so the
    whole realistic backtester is configured, never hard-coded (Ground Rule 2).
    """
    return Backtester(
        IndianCostModel(config.costs),
        DepthAwareSlippage(config.slippage),
        initial_capital=config.backtest.initial_capital_inr,
        execution_delay_bars=config.backtest.execution_delay_bars,
    )
