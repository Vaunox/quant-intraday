"""Risk-managed portfolio manager (no ML) for the multi-ETF track.

Implements the pre-registered vol-targeted risk-parity allocator
(`docs/etf_rotation/pm_viability_prereg.md`): inverse-volatility weights across the risk
assets, scaled by a portfolio volatility target via gross-exposure-to-cash (the drawdown
control), long/flat with no leverage. Pure over an aligned price panel; reuses
:func:`~quant.research.etf.rotation.backtest_weights` for the cost-aware backtest.

No return forecasting, no ML — this answers the separate "is there a deployable PM?" question
that the ML-rotation NO-GO did not address.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from quant.research.etf.benchmark import EquityCurve, month_end_indices
from quant.research.etf.costs import ETFCostModel
from quant.research.etf.rotation import backtest_weights


@dataclass(frozen=True, slots=True)
class PMConfig:
    """Pre-registered, convention-default PM parameters (not tuned).

    Attributes:
        vol_lookback: Trailing sessions for realized-vol estimates.
        target_vol: Annualised portfolio volatility target driving gross exposure.
    """

    vol_lookback: int = 63
    target_vol: float = 0.10


def realized_vol(prices: Sequence[float], end: int, window: int) -> float:
    """Annualised realized volatility over the ``window`` sessions ending at ``end``."""
    rets = [prices[i] / prices[i - 1] - 1.0 for i in range(end - window + 1, end + 1)]
    return float(np.std(rets, ddof=1) * np.sqrt(252.0)) if len(rets) > 1 else 0.0


def risk_parity_schedule(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    cfg: PMConfig,
    *,
    cash_symbol: str,
) -> dict[int, dict[str, float]]:
    """Monthly vol-targeted risk-parity target weights (gross scaled to cash, no leverage).

    At each month-end with enough history: inverse-vol raw weights across risk assets; estimate
    the trailing volatility of that raw portfolio; set gross ``G = min(1, target/port_vol)`` and
    hold ``1 - G`` in cash.

    Args:
        dates: Aligned session dates.
        prices: All-leg prices (risk + cash), aligned.
        cfg: PM parameters.
        cash_symbol: The cash leg.

    Returns:
        Rebalance date-index -> target weights (sum to 1, incl. cash).
    """
    risk = [s for s in prices if s != cash_symbol]
    schedule: dict[int, dict[str, float]] = {}
    for t in month_end_indices(dates):
        if t < cfg.vol_lookback:
            continue
        inv = {a: 1.0 / max(realized_vol(prices[a], t, cfg.vol_lookback), 1e-6) for a in risk}
        total_inv = sum(inv.values())
        raw = {a: inv[a] / total_inv for a in risk}
        port_rets = [
            sum(raw[a] * (prices[a][s] / prices[a][s - 1] - 1.0) for a in risk)
            for s in range(t - cfg.vol_lookback + 1, t + 1)
        ]
        port_vol = float(np.std(port_rets, ddof=1) * np.sqrt(252.0)) if len(port_rets) > 1 else 0.0
        gross = min(1.0, cfg.target_vol / port_vol) if port_vol > 0 else 1.0
        weights = dict.fromkeys(prices, 0.0)
        for a in risk:
            weights[a] = gross * raw[a]
        weights[cash_symbol] = 1.0 - gross
        schedule[t] = weights
    return schedule


def run_risk_parity_pm(
    dates: Sequence[date],
    prices: Mapping[str, Sequence[float]],
    cost_model: ETFCostModel,
    cfg: PMConfig,
    *,
    cash_symbol: str,
    capital: float = 100_000.0,
) -> EquityCurve:
    """Build the vol-targeted risk-parity schedule and backtest it net of costs."""
    schedule = risk_parity_schedule(dates, prices, cfg, cash_symbol=cash_symbol)
    return backtest_weights(dates, prices, schedule, cost_model, capital=capital)
