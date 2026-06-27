"""CNC cost model + monthly-rebalance backtester (Phase 3X.6).

The intraday cost model (``IndianCostModel``) is MIS-only (sell-side STT, no overnight). Delivery
(CNC) is a different schedule — **STT 0.10% on *both* legs** dominates — so this module prices the
CNC round trip itemised (matching a discount-broker delivery calculator) at ≈ 0.22%, and simulates
a monthly book that holds across sessions (no square-off).

The backtester is deliberately monthly-simple: at each rebalance the book moves toward the target
weights, but only for names whose weight change clears the **no-trade band** (the single
highest-impact cost lever) — the band is applied *before* costing. Intra-period drift is ignored
(a standard, documented approximation at monthly frequency). Two independent computations of the
net-return series — an explicit per-rebalance loop and a vectorised re-derivation — are reconciled
to floating-point noise, the §4b.8 two-engine check.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.research.validation.errors import BacktestError


@dataclass(frozen=True, slots=True)
class CncCostModel:
    """Itemised Indian **delivery (CNC)** transaction cost; round trip ≈ 0.22%.

    Per-leg rates as fractions of turnover. STT is charged on **both** legs for delivery (the key
    difference from MIS); stamp duty on the buy leg; exchange/SEBI per side; GST on
    (brokerage + exchange + SEBI). Brokerage defaults to 0 (zero-brokerage delivery).
    """

    stt_rate: float = 0.001  # 0.10% per leg (delivery) — both buy and sell
    stamp_buy_rate: float = 0.00015  # 0.015% buy side
    exchange_rate: float = 0.00003  # per side
    sebi_rate: float = 0.000001  # per side
    gst_rate: float = 0.18
    brokerage_rate: float = 0.0  # zero-brokerage delivery

    def _gst(self) -> float:
        return self.gst_rate * (self.brokerage_rate + self.exchange_rate + self.sebi_rate)

    def buy_leg_rate(self) -> float:
        """Total cost rate of a buy leg (STT + stamp + exchange + SEBI + GST + brokerage)."""
        return (
            self.stt_rate
            + self.stamp_buy_rate
            + self.exchange_rate
            + self.sebi_rate
            + self._gst()
            + self.brokerage_rate
        )

    def sell_leg_rate(self) -> float:
        """Total cost rate of a sell leg (STT + exchange + SEBI + GST + brokerage; no stamp)."""
        return (
            self.stt_rate + self.exchange_rate + self.sebi_rate + self._gst() + self.brokerage_rate
        )

    def round_trip_rate(self) -> float:
        """Buy leg + sell leg ≈ 0.0022 — the CNC round-trip cost as a fraction of notional."""
        return self.buy_leg_rate() + self.sell_leg_rate()


@dataclass(frozen=True, slots=True)
class MonthlyBacktestResult:
    """Per-rebalance gross / net book return, CNC cost, and one-way turnover (all fractions)."""

    gross_return: pd.Series
    net_return: pd.Series
    cost: pd.Series
    turnover: pd.Series
    held_weights: pd.DataFrame  # the weights actually held each period (post-band)


def held_weights(target_weights: pd.DataFrame, *, no_trade_band: float) -> pd.DataFrame:
    """Return the weights actually held each rebalance after applying the relative no-trade band.

    A name is only retraded when its target moves more than ``no_trade_band`` (relative to the
    larger of its target / currently-held weight); otherwise the held weight is carried. Entering
    (held 0) and exiting (target 0) positions always trade. Drift between rebalances is ignored.

    Raises:
        BacktestError: If ``no_trade_band`` is negative.
    """
    if no_trade_band < 0:
        raise BacktestError(f"no_trade_band must be >= 0, got {no_trade_band}")
    target = target_weights.fillna(0.0).to_numpy(dtype="float64")
    n_periods, n_names = target.shape
    held = np.zeros_like(target)
    current = np.zeros(n_names, dtype="float64")
    for t in range(n_periods):
        want = target[t]
        reference = np.maximum(np.abs(want), np.abs(current))
        threshold = no_trade_band * reference
        move = np.abs(want - current) > threshold
        current = np.where(move, want, current)
        held[t] = current
    return pd.DataFrame(held, index=target_weights.index, columns=target_weights.columns)


def monthly_backtest(
    target_weights: pd.DataFrame,
    period_returns: pd.DataFrame,
    *,
    cost_model: CncCostModel,
    no_trade_band: float = 0.0,
) -> MonthlyBacktestResult:
    """Simulate the monthly book; return per-rebalance gross/net return, cost, and turnover.

    Args:
        target_weights: index = rebalance date, columns = symbol, the desired weights (rows ≤ 1).
        period_returns: same shape — each name's realised return over the hold period that *starts*
            at that rebalance (e.g. the P3X.3 forward return).
        cost_model: the CNC cost model (its round-trip rate scales the per-rebalance turnover).
        no_trade_band: relative band suppressing small reweights before costing.

    Raises:
        BacktestError: If the two frames are not aligned.
    """
    if not target_weights.index.equals(period_returns.index) or not target_weights.columns.equals(
        period_returns.columns
    ):
        raise BacktestError("target_weights and period_returns must share index and columns")

    held = held_weights(target_weights, no_trade_band=no_trade_band)
    held_arr = held.to_numpy(dtype="float64")
    rate = cost_model.round_trip_rate()

    # One-way turnover = sum of |Δ held weight| vs the previous held row (first row vs flat).
    previous = np.vstack([np.zeros((1, held_arr.shape[1])), held_arr[:-1]])
    turnover = np.abs(held_arr - previous).sum(axis=1)
    cost = turnover * rate
    gross = np.nansum(held_arr * period_returns.to_numpy(dtype="float64"), axis=1)
    net = gross - cost

    index = target_weights.index
    return MonthlyBacktestResult(
        gross_return=pd.Series(gross, index=index, name="gross_return"),
        net_return=pd.Series(net, index=index, name="net_return"),
        cost=pd.Series(cost, index=index, name="cost"),
        turnover=pd.Series(turnover, index=index, name="turnover"),
        held_weights=held,
    )


def reconcile_net_returns(
    target_weights: pd.DataFrame,
    period_returns: pd.DataFrame,
    *,
    cost_model: CncCostModel,
    no_trade_band: float = 0.0,
) -> float:
    """Return the max abs difference between the vectorised and an explicit-loop net series.

    The vectorised engine is :func:`monthly_backtest`; the second engine re-derives the same
    net-return series with an independent per-rebalance loop (notional accounting). They must agree
    to floating-point noise — the §4b.8 two-engine reconciliation.
    """
    vectorised = monthly_backtest(
        target_weights, period_returns, cost_model=cost_model, no_trade_band=no_trade_band
    ).net_return.to_numpy(dtype="float64")

    held = held_weights(target_weights, no_trade_band=no_trade_band).to_numpy(dtype="float64")
    returns = period_returns.fillna(0.0).to_numpy(dtype="float64")
    rate = cost_model.round_trip_rate()
    loop_net = np.empty(held.shape[0], dtype="float64")
    previous: npt.NDArray[np.float64] = np.zeros(held.shape[1], dtype="float64")
    for t in range(held.shape[0]):
        current = held[t]
        turnover = float(np.abs(current - previous).sum())
        gross = float(np.dot(current, returns[t]))
        loop_net[t] = gross - turnover * rate
        previous = current
    return float(np.max(np.abs(vectorised - loop_net)))
