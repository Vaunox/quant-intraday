"""The validation report (Deep Dive #2 §4b.8 output contract; the P2.9 deliverable).

*"Output contract of Module 4b: a validation report per strategy containing the CPCV path-Sharpe
distribution, Deflated Sharpe, PBO, honest trial count, full-cost walk-forward equity curve, and
the robustness battery results — sufficient to make a binary trade/don't-trade decision."* This
module is that report: a frozen :class:`ValidationReport` bundling every piece of evidence plus
the seven-point :class:`~quant.research.reports.killgate.KillGateVerdict`, and a text renderer.

It also holds the small, pure statistics the kill-gate's cost-inclusive criteria need but that
live nowhere else yet:

* :func:`round_trip_cost_fraction` — a representative all-in round-trip cost (Indian cost model +
  slippage) as a fraction of notional, so the CPCV path-Sharpe can be computed **net** (criterion
  1 is *"after full Indian costs and slippage"* — gross numbers are fantasy here).
* :func:`net_event_returns` — gross per-event strategy returns minus position-scaled round-trip
  costs (one round trip per triple-barrier event: enter at ``t0``, exit at the barrier).
* :func:`profit_factor` / :func:`trade_concentration` — the criterion-5 concentration checks.
* :func:`regime_breakdown` — per-regime mean net return + counts for criterion 7.

The assembly that *runs* the model and validation engine to produce these inputs is orchestration
(:mod:`quant.research.pipeline.validation`); this module stays a pure bundler + renderer + the
stat primitives, so it is exhaustively testable without training anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.types import Side
from quant.research.reports.killgate import KillGateVerdict
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.slippage import DepthAwareSlippage

#: Basis points per unit fraction (1 bp = 1e-4), matching the slippage model's convention.
_BPS_PER_UNIT = 1e4


def round_trip_cost_fraction(
    cost_model: IndianCostModel,
    slippage_model: DepthAwareSlippage,
    *,
    price: float,
    quantity: int,
    liquidity: float,
) -> float:
    """Return a representative round-trip cost as a fraction of notional (entry buy + exit sell).

    Combines the itemised Indian transaction cost (both legs) with twice the one-way slippage
    (the book is walked adversely on both entry and exit). Computed once on a representative
    trade — a typical price, a notional-sized quantity, and the median bar liquidity — then
    applied per event by :func:`net_event_returns`. Brokerage's per-order ₹20 cap makes the
    fraction size-dependent, which is why a representative notional is used rather than a flat
    rate (Deep Dive #2 §4b.6).

    Args:
        cost_model: The Indian transaction-cost model.
        slippage_model: The size/depth-aware slippage model.
        price: A representative fill price (> 0), e.g. the universe's median close.
        quantity: A representative order size in shares (> 0), e.g. a notional / price.
        liquidity: Representative bar liquidity (shares), e.g. the median bar volume.

    Returns:
        The round-trip cost as a fraction of the round-trip notional.
    """
    notional = price * quantity
    buy_cost = cost_model.cost_for_fill(Side.BUY, price, quantity).total
    sell_cost = cost_model.cost_for_fill(Side.SELL, price, quantity).total
    one_way_slippage = slippage_model.slippage_bps(quantity, liquidity) / _BPS_PER_UNIT
    return (buy_cost + sell_cost) / notional + 2.0 * one_way_slippage


def net_event_returns(
    positions: npt.NDArray[np.float64] | pd.Series,
    gross_returns: npt.NDArray[np.float64] | pd.Series,
    round_trip_cost: float,
) -> npt.NDArray[np.float64]:
    """Return per-event net returns: ``position·gross - |position|·round_trip_cost``.

    Each triple-barrier event is one round trip (enter at ``t0``, exit at the barrier), so the
    round-trip cost is charged once per event, scaled by the position size taken (a fractional
    conviction position pays proportionally less, matching the notional traded). This is the
    cost-inclusive return the kill-gate's CPCV/DSR/concentration criteria judge.
    """
    pos = np.asarray(positions, dtype="float64").ravel()
    gross = np.asarray(gross_returns, dtype="float64").ravel()
    return np.asarray(pos * gross - np.abs(pos) * round_trip_cost, dtype="float64")


def profit_factor(net_returns: npt.NDArray[np.float64] | pd.Series) -> float:
    """Return the profit factor: gross profit / gross loss over the net per-trade returns.

    ``inf`` if there are no losing trades (all wins), ``0.0`` if there are no winning trades.
    A profit factor near 1 means wins barely cover losses — a thin, fragile edge (criterion 5).
    """
    values = np.asarray(net_returns, dtype="float64").ravel()
    gross_profit = float(values[values > 0.0].sum())
    gross_loss = float(-values[values < 0.0].sum())
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


def trade_concentration(net_returns: npt.NDArray[np.float64] | pd.Series) -> float:
    """Return the largest single winning trade's share of total gross profit, in ``[0, 1]``.

    A value near 1 means one outlier carries the whole edge — the criterion-5 red flag. ``0.0``
    when there is no gross profit (nothing to concentrate).
    """
    values = np.asarray(net_returns, dtype="float64").ravel()
    wins = values[values > 0.0]
    gross_profit = float(wins.sum())
    if gross_profit == 0.0:
        return 0.0
    return float(wins.max()) / gross_profit


def regime_breakdown(
    regimes: npt.NDArray[np.intp] | pd.Series,
    net_returns: npt.NDArray[np.float64] | pd.Series,
    n_regimes: int,
) -> tuple[dict[int, float], dict[int, int]]:
    """Return ``(mean net return per regime, observation count per regime)`` for criterion 7.

    A regime with no observations is omitted from both maps (it cannot be judged for stability).
    """
    labels = np.asarray(regimes, dtype=np.intp).ravel()
    values = np.asarray(net_returns, dtype="float64").ravel()
    means: dict[int, float] = {}
    counts: dict[int, int] = {}
    for regime in range(n_regimes):
        mask = labels == regime
        count = int(mask.sum())
        if count > 0:
            means[regime] = float(values[mask].mean())
            counts[regime] = count
    return means, counts


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    """Headline numbers from the full-cost, next-bar-open walk-forward backtest (P2.1)."""

    net_pnl: float
    final_equity: float
    max_drawdown_pct: float
    n_fills: int


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The complete §4b.8 validation report: every piece of evidence + the kill-gate verdict."""

    model_id: str | None
    data_version: str
    feature_set_version: str
    label_version: str
    n_obs: int
    n_trials: int
    periods_per_year: float
    # CPCV path-Sharpe distribution (annualised, net of costs).
    cpcv_num_paths: int
    cpcv_median_sharpe: float
    cpcv_mean_sharpe: float
    cpcv_std_sharpe: float
    cpcv_worst_sharpe: float
    cpcv_fraction_negative: float
    # Multiple-testing-aware statistics.
    deflated_sharpe_ratio: float
    pbo: float
    # Concentration (criterion 5).
    profit_factor: float
    trade_concentration: float
    # Walk-forward equity (full-cost, next-bar-open).
    walk_forward: WalkForwardSummary
    # Robustness battery (P2.8) + regimes (criterion 7).
    robustness_passed: bool
    robustness_detail: str
    regime_mean_returns: Mapping[int, float]
    # The verdict.
    verdict: KillGateVerdict

    @property
    def passed(self) -> bool:
        """Whether the kill-gate verdict is PASS (proceed toward capital)."""
        return self.verdict.passed

    def render(self) -> str:
        """Render the full report as a fixed-width text block (the trade/don't-trade document)."""
        regimes = ", ".join(
            f"r{r}={self.regime_mean_returns[r]:+.4f}" for r in sorted(self.regime_mean_returns)
        )
        lines = [
            "VALIDATION REPORT — seven-point kill-gate",
            "=" * 72,
            f"  candidate         : {self.model_id}",
            f"  data / feature    : {self.data_version} / {self.feature_set_version}",
            f"  label version     : {self.label_version}",
            f"  observations      : {self.n_obs}   honest trial count: {self.n_trials}",
            f"  annualisation     : {self.periods_per_year:.1f} periods/year",
            "-" * 72,
            "  CPCV path-Sharpe distribution (annualised, NET of costs):",
            f"    paths={self.cpcv_num_paths}  median={self.cpcv_median_sharpe:+.3f}  "
            f"mean={self.cpcv_mean_sharpe:+.3f}  std={self.cpcv_std_sharpe:.3f}",
            f"    worst={self.cpcv_worst_sharpe:+.3f}  "
            f"fraction-negative={self.cpcv_fraction_negative:.3f}",
            f"  Deflated Sharpe Ratio : {self.deflated_sharpe_ratio:.3f}",
            f"  PBO                   : {self.pbo:.3f}",
            f"  profit factor         : {self.profit_factor:.3f}   "
            f"top-trade share: {self.trade_concentration:.3f}",
            "  Walk-forward (full-cost, next-bar-open):",
            f"    net P&L={self.walk_forward.net_pnl:+.2f}  "
            f"final equity={self.walk_forward.final_equity:.2f}  "
            f"max DD={self.walk_forward.max_drawdown_pct:.2%}  fills={self.walk_forward.n_fills}",
            f"  robustness battery    : {'PASS' if self.robustness_passed else 'FAIL'} "
            f"({self.robustness_detail})",
            f"  regime mean net return: {regimes}",
            "=" * 72,
            "",
            self.verdict.render(),
        ]
        return "\n".join(lines)
