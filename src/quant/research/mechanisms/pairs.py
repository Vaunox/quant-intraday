"""Cointegration pairs / statistical-arbitrage mechanism (Part VI / P7.2).

The second mechanism study (pursued because P7.1 did not clear). The edge is **market-neutral
spread mean-reversion** on genuinely **cointegrated** pairs — not mere correlation. Two stocks
whose prices share a common stochastic trend have a stationary spread; when the spread deviates
from its formation mean it tends to revert, and a dollar-neutral long-cheap / short-rich position
harvests that reversion (pre-registration: ``docs/mechanisms/cointegration_pairs_prereg.md``).

This is a statistical relationship, not a directional bar-data prediction, so it plugs into the
**existing** seven-point kill-gate via the Part-VI harness (P6.1). It runs on **real data** — the
survivorship-free NSE daily panel (``data/nifty_panel/``) — needing only prices, so unlike P7.1 it
is fully judgeable.

**Point-in-time by construction (Inviolable Rule 2).** For each monthly rebalance the pairs are
re-selected on a **trailing formation window ending at the decision date** via the Engle-Granger
cointegration test (``statsmodels``); the hedge ratio and the spread mean/std are estimated on that
same trailing window; the position is taken on the spread's current z-score and the return is
realised over the **following** month. No future data enters any decision. The cointegration
**test choice + its parameters** (formation length, p-value cutoff, z-cap, pair count) are a
searched configuration and are charged to the trial count (P6.2) by the study's config panel.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd
from statsmodels.tsa.stattools import coint

from quant.core.logging import get_logger
from quant.research.mechanisms.errors import MechanismDataError, SpecError

_logger = get_logger(__name__)

#: Trading days per year, for annualising the monthly path-Sharpe.
MONTHLY_PERIODS_PER_YEAR = 12.0


@dataclass(frozen=True, slots=True)
class PairModel:
    """One cointegrated pair fitted on a formation window (all estimated point-in-time).

    The spread is ``log(y) - beta*log(x)``; ``mu`` / ``sigma`` are its formation mean / std, used
    to z-score the live spread. ``pvalue`` is the Engle-Granger cointegration p-value (lower = more
    cointegrated).
    """

    y: str
    x: str
    beta: float
    mu: float
    sigma: float
    pvalue: float


def log_price_panel(close_panel: pd.DataFrame) -> pd.DataFrame:
    """Return the sorted log-price panel (non-positive closes blanked to NaN), index/cols preserved.

    A typed helper around ``np.log`` (which the stubs type as ``ndarray``): the result stays a
    :class:`~pandas.DataFrame` so the rest of the module works in label space.
    """
    sorted_panel = close_panel.sort_index()
    masked = sorted_panel.where(sorted_panel > 0.0)
    return pd.DataFrame(
        np.log(masked.to_numpy(dtype="float64")), index=masked.index, columns=masked.columns
    )


def select_cointegrated_pairs(
    formation_log_prices: pd.DataFrame,
    *,
    pvalue_max: float,
    max_pairs: int,
    min_correlation: float,
) -> list[PairModel]:
    """Select the most-cointegrated pairs on a formation window (Engle-Granger).

    Args:
        formation_log_prices: log-price columns over the trailing formation window (one per name).
        pvalue_max: keep only pairs with an Engle-Granger p-value at/below this.
        max_pairs: cap on the number of pairs returned (lowest p-value first).
        min_correlation: cheap pre-filter — only test pairs whose formation log-price correlation
            is at least this (cointegration implies co-movement; skips the obvious non-pairs fast).

    Returns:
        Fitted :class:`PairModel` records, lowest p-value first, at most ``max_pairs``.
    """
    columns = [
        str(c) for c in formation_log_prices.columns if formation_log_prices[c].notna().all()
    ]
    frame = formation_log_prices[columns]
    if frame.shape[0] < 30 or len(columns) < 2:
        return []  # too little history / too few names to fit a pair
    corr = np.corrcoef(frame.to_numpy(dtype="float64"), rowvar=False)
    pos = {col: i for i, col in enumerate(columns)}
    fitted: list[PairModel] = []
    for a, b in combinations(columns, 2):
        if abs(float(corr[pos[a], pos[b]])) < min_correlation:
            continue
        model = _fit_pair(frame[a], frame[b], a, b)
        if model is not None and model.pvalue <= pvalue_max:
            fitted.append(model)
    fitted.sort(key=lambda m: m.pvalue)
    return fitted[:max_pairs]


class CointegrationPairsSpec:
    """A market-neutral cointegration-pairs :class:`~quant.research.mechanisms.spec.StrategySpec`.

    Precomputes the per-month net return of a dollar-neutral spread-reversion book: each month,
    re-select cointegrated pairs on the trailing formation window, take a position of
    ``-clip(z, +/-z_cap)/z_cap`` on each pair's spread (bet against the deviation), realise the
    spread return over the following month, average equal-weight across pairs, and charge the CNC
    round-trip cost on the rebalanced gross exposure. Fully point-in-time; ``fit`` is a no-op (the
    monthly re-selection already uses only trailing data).
    """

    def __init__(
        self,
        close_panel: pd.DataFrame,
        *,
        round_trip_cost: float,
        formation_days: int = 252,
        pvalue_max: float = 0.05,
        max_pairs: int = 5,
        z_cap: float = 2.0,
        min_correlation: float = 0.7,
        name: str = "cointegration_pairs",
    ) -> None:
        """Bind the spec to a close panel and the (searched) strategy configuration.

        Args:
            close_panel: wide daily close matrix (``DatetimeIndex`` rows, candidate symbols cols).
            round_trip_cost: CNC round-trip cost fraction charged per monthly rebalance (Rule 4).
            formation_days: trailing window (trading days) the pairs are selected/fitted on.
            pvalue_max: Engle-Granger cointegration p-value cutoff.
            max_pairs: maximum pairs held per month.
            z_cap: spread z-score cap (position is ``-clip(z, +/-z_cap)/z_cap``  in  [-1, 1]).
            min_correlation: formation-correlation pre-filter for the pair search.
            name: mechanism name (logged + used in the trial count).

        Raises:
            SpecError: On a non-positive cost or degenerate parameters.
            MechanismDataError: If the panel yields no tradeable rebalance month.
        """
        if round_trip_cost < 0.0:
            raise SpecError(f"round_trip_cost must be non-negative, got {round_trip_cost}")
        if formation_days < 30 or z_cap <= 0.0 or max_pairs < 1:
            raise SpecError("degenerate pairs configuration (formation_days/z_cap/max_pairs)")
        self._name = name
        log_prices = log_price_panel(close_panel)
        net, label_times = _build_monthly_returns(
            log_prices,
            round_trip_cost=round_trip_cost,
            formation_days=formation_days,
            pvalue_max=pvalue_max,
            max_pairs=max_pairs,
            z_cap=z_cap,
            min_correlation=min_correlation,
        )
        if net.empty:
            raise MechanismDataError(
                f"{name}: no tradeable rebalance month produced a pairs return on this panel "
                "(no cointegrated pairs found in any formation window)"
            )
        self._net_returns = net
        self._label_times = label_times

    @property
    def name(self) -> str:
        """The mechanism name."""
        return self._name

    @property
    def label_times(self) -> pd.Series:
        """Monthly ``t0 -> t1`` holding spans (the CPCV purge/embargo timeline)."""
        return self._label_times

    @property
    def n_periods(self) -> int:
        """Number of rebalance months with a realised return."""
        return int(self._net_returns.shape[0])

    def fit(self, train_positions: npt.NDArray[np.intp]) -> None:
        """No-op: monthly re-selection is already trailing/point-in-time."""
        return None

    def event_returns(self, positions: npt.NDArray[np.intp]) -> pd.Series:
        """Net per-month book returns at ``positions``."""
        return self._net_returns.iloc[positions]


def _fit_pair(log_y: pd.Series, log_x: pd.Series, y: str, x: str) -> PairModel | None:
    """Engle-Granger fit of one pair on the formation window, or ``None`` if degenerate."""
    try:
        _, pvalue, _ = coint(log_y.to_numpy(), log_x.to_numpy())
    except (ValueError, np.linalg.LinAlgError):
        return None
    # Hedge ratio via OLS of y on x (with intercept); spread = y - beta*x.
    x_arr = log_x.to_numpy(dtype="float64")
    y_arr = log_y.to_numpy(dtype="float64")
    design = np.vstack([x_arr, np.ones_like(x_arr)]).T
    beta, intercept = np.linalg.lstsq(design, y_arr, rcond=None)[0]
    spread = y_arr - beta * x_arr - intercept
    sigma = float(spread.std(ddof=1))
    if not np.isfinite(sigma) or sigma == 0.0:
        return None
    return PairModel(
        y=y, x=x, beta=float(beta), mu=float(spread.mean()), sigma=sigma, pvalue=float(pvalue)
    )


def _build_monthly_returns(
    log_prices: pd.DataFrame,
    *,
    round_trip_cost: float,
    formation_days: int,
    pvalue_max: float,
    max_pairs: int,
    z_cap: float,
    min_correlation: float,
) -> tuple[pd.Series, pd.Series]:
    """Compute the point-in-time monthly net return series + its ``t0 -> t1`` label times."""
    # Month-end decision dates that have a full formation window behind them and a month ahead.
    month_ends = _month_end_positions(cast(pd.DatetimeIndex, log_prices.index))
    decisions = [p for p in month_ends if p >= formation_days]
    returns: list[float] = []
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for i, pos in enumerate(decisions[:-1]):
        next_pos = decisions[i + 1]
        formation = log_prices.iloc[pos - formation_days : pos + 1]
        pairs = select_cointegrated_pairs(
            formation, pvalue_max=pvalue_max, max_pairs=max_pairs, min_correlation=min_correlation
        )
        if not pairs:
            continue
        period_return = _period_book_return(
            log_prices, pos, next_pos, pairs, z_cap=z_cap, round_trip_cost=round_trip_cost
        )
        if period_return is None:
            continue
        returns.append(period_return)
        starts.append(pd.Timestamp(log_prices.index[pos]))
        ends.append(pd.Timestamp(log_prices.index[next_pos]))
    index = pd.DatetimeIndex(starts, name="rebalance")
    net = pd.Series(returns, index=index, name="net")
    label_times = pd.Series(ends, index=index, name="t1")
    return net, label_times


def _period_book_return(
    log_prices: pd.DataFrame,
    pos: int,
    next_pos: int,
    pairs: Sequence[PairModel],
    *,
    z_cap: float,
    round_trip_cost: float,
) -> float | None:
    """Equal-weight net book return over one month for the selected pairs (or ``None``)."""
    row_now = log_prices.iloc[pos]
    row_next = log_prices.iloc[next_pos]
    pair_returns: list[float] = []
    gross = 0.0
    for pair in pairs:
        spread_now = row_now.get(pair.y, np.nan) - pair.beta * row_now.get(pair.x, np.nan)
        spread_next = row_next.get(pair.y, np.nan) - pair.beta * row_next.get(pair.x, np.nan)
        if not np.isfinite(spread_now) or not np.isfinite(spread_next):
            continue
        z = (float(spread_now) - pair.mu) / pair.sigma
        position = (
            -float(np.clip(z, -z_cap, z_cap)) / z_cap
        )  # bet against the deviation, in [-1, 1]
        # Δspread (mu cancels) is the dollar-neutral spread return realised over the month.
        delta_spread = float(spread_next) - float(spread_now)
        pair_returns.append(position * delta_spread)
        gross += abs(position)
    if not pair_returns:
        return None
    gross_return = float(np.mean(pair_returns))
    # Charge the round-trip cost on the rebalanced average gross exposure (conservative).
    cost = round_trip_cost * gross / len(pair_returns)
    return gross_return - cost


def _month_end_positions(index: pd.DatetimeIndex) -> list[int]:
    """Integer positions of the last trading day of each calendar month in ``index``."""
    n = len(index)
    if n == 0:
        return []
    # year*100 + month per row (tz-safe, unlike ``to_period`` which warns on tz-aware indices).
    key = index.year.to_numpy() * 100 + index.month.to_numpy()
    return [i for i in range(n) if i == n - 1 or key[i] != key[i + 1]]


__all__ = [
    "MONTHLY_PERIODS_PER_YEAR",
    "CointegrationPairsSpec",
    "PairModel",
    "log_price_panel",
    "select_cointegrated_pairs",
]
