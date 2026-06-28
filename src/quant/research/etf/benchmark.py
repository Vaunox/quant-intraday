"""Step 3 fixed-weight benchmark for the multi-ETF rotation track.

The line the ML must beat (SPEC_MultiETF_Rotation.md Section 4): an **equal-weight basket of
the frozen universe, rebalanced monthly, net of the Step 2 cost model**. Success for the ML
is beating this on *excess* return after both pay the same regressive DP/spread costs — not
"positive Sharpe". This module is pure over an aligned daily total-return price panel; the
Yahoo fetch lives in the thin ``scripts/etf_benchmark.py`` shim (Ground Rule 3).

Cash-leg honesty: the LIQUIDBEES leg's total return is modeled with an explicit annual yield,
because Yahoo's adjusted close understates it (~3% measured vs the ~6% overnight rate the leg
actually earns). The cash leg is the pivot of the excess-return comparison, so getting it
right matters more than feed convenience.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from quant.research.etf.costs import ETFCostModel, Side
from quant.research.validation.metrics import sharpe_ratio


@dataclass(frozen=True, slots=True)
class EquityCurve:
    """A net-of-cost equity path.

    Attributes:
        dates: Session dates, ascending.
        equity: Portfolio value at each date (same length as ``dates``).
    """

    dates: list[date]
    equity: list[float]

    def daily_returns(self) -> list[float]:
        """Simple day-over-day returns (length ``len(equity) - 1``)."""
        eq = self.equity
        return [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]

    def cagr(self, periods_per_year: float = 252.0) -> float:
        """Compound annual growth rate implied by the path."""
        periods = len(self.equity) - 1
        if periods <= 0 or self.equity[0] <= 0:
            raise ValueError("need a positive multi-point equity curve for CAGR")
        return float((self.equity[-1] / self.equity[0]) ** (periods_per_year / periods)) - 1.0

    def max_drawdown(self) -> float:
        """Worst peak-to-trough decline as a negative fraction (0 if monotonic)."""
        peak = self.equity[0]
        worst = 0.0
        for value in self.equity:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        return worst

    def ann_sharpe(self, periods_per_year: float = 252.0) -> float:
        """Annualised Sharpe of the daily returns (reuses the gate's metric)."""
        return sharpe_ratio(self.daily_returns(), periods_per_year=periods_per_year)


def month_end_indices(dates: Sequence[date]) -> list[int]:
    """Index positions that are the last trading day of their calendar month."""
    out: list[int] = []
    for i, day in enumerate(dates):
        is_last = i + 1 == len(dates) or (dates[i + 1].year, dates[i + 1].month) != (
            day.year,
            day.month,
        )
        if is_last:
            out.append(i)
    return out


def synthetic_cash_prices(dates: Sequence[date], annual_yield: float) -> list[float]:
    """A total-return price series for the cash leg, compounding at ``annual_yield``.

    Approximated on a per-trading-day basis (252/yr), which is sufficient for a benchmark.
    """
    daily = float((1.0 + annual_yield) ** (1.0 / 252.0)) - 1.0
    return [(1.0 + daily) ** i for i in range(len(dates))]


def equal_weight_rebalanced(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    cost_model: ETFCostModel,
    *,
    capital: float = 100_000.0,
) -> EquityCurve:
    """Equal-weight, monthly-rebalanced benchmark equity curve, net of costs.

    Allocates ``capital`` equally across the legs (paying buy costs at inception), lets the
    legs drift with their total-return prices, and on each month-end rebalances back to equal
    weight, paying the Step 2 cost model on each leg's traded delta (buy or sell).

    Args:
        dates: Aligned session dates, ascending.
        prices: Symbol -> aligned total-return price series (cash leg pre-synthesised).
        cost_model: The Step 2 cost model.
        capital: Starting capital (Rs).

    Returns:
        The net-of-cost :class:`EquityCurve`.

    Raises:
        ValueError: If ``prices`` is empty or series lengths disagree with ``dates``.
    """
    symbols = list(prices)
    if not symbols:
        raise ValueError("need at least one leg")
    if any(len(prices[s]) != len(dates) for s in symbols):
        raise ValueError("price series must align with dates")
    n = len(symbols)

    target0 = capital / n
    init_cost = sum(cost_model.trade_cost(s, target0, side="buy").total for s in symbols)
    portfolio = capital - init_cost
    legs = dict.fromkeys(symbols, portfolio / n)

    rebalance = frozenset(month_end_indices(dates))
    equity = [portfolio]
    for t in range(1, len(dates)):
        for s in symbols:
            legs[s] *= prices[s][t] / prices[s][t - 1]
        portfolio = sum(legs.values())
        if t in rebalance:
            target = portfolio / n
            cost = 0.0
            for s in symbols:
                delta = target - legs[s]
                side: Side = "buy" if delta > 0 else "sell"
                cost += cost_model.trade_cost(s, abs(delta), side=side).total
                legs[s] = target
            portfolio -= cost
            scale = portfolio / (target * n)
            legs = {s: legs[s] * scale for s in symbols}
        equity.append(portfolio)
    return EquityCurve(list(dates), equity)


def buy_and_hold(
    dates: Sequence[date],
    prices: Sequence[float],
    symbol: str,
    cost_model: ETFCostModel,
    *,
    capital: float = 100_000.0,
) -> EquityCurve:
    """Buy-and-hold one leg (a Section 4 secondary floor), net of the entry cost only."""
    if len(prices) != len(dates):
        raise ValueError("price series must align with dates")
    deployed = capital - cost_model.trade_cost(symbol, capital, side="buy").total
    equity = [deployed * prices[t] / prices[0] for t in range(len(dates))]
    return EquityCurve(list(dates), equity)
