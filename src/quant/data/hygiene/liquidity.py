"""Universe liquidity screen + ESM/T2T exclusion (Deep Dive #1 §1.3.6).

*"Restrict to genuinely liquid names (high average daily value, tight median spread,
consistent volume). Illiquid names destroy you on slippage and make backtests
fantastically optimistic."* Plus the SEBI rule (Inviolable Rule 6): **exclude ESM/T2T**
names, which cannot be traded intraday.

:class:`LiquidityScreen` applies the configured thresholds (``UniverseEligibility``:
min ADV, max spread, ESM/T2T toggle) to per-symbol :class:`LiquidityMetrics`, returning
the eligible names and a reasoned rejection for each excluded one. :func:`average_daily_value`
computes ADV from bars; median spread is depth-derived (5-level book, a later pass) and is
passed in, so this stays a pure, testable screen.
"""

from collections.abc import Sequence, Set
from dataclasses import dataclass

import pandas as pd

from quant.core.calendar import IST
from quant.core.config import UniverseEligibility
from quant.core.logging import get_logger
from quant.data.store import serde

_logger = get_logger(__name__)

#: Rejection reason codes (stable strings, suitable for logging/metrics).
REASON_ADV_BELOW_MIN = "adv_below_min"
REASON_SPREAD_TOO_WIDE = "spread_too_wide"
REASON_ESM_T2T_EXCLUDED = "esm_t2t_excluded"


@dataclass(frozen=True, slots=True)
class LiquidityMetrics:
    """Per-symbol liquidity inputs to the screen.

    Attributes:
        symbol: The instrument.
        adv_inr: Average daily traded value in INR (see :func:`average_daily_value`).
        median_spread_bps: Median bid-ask spread in basis points (depth-derived).
    """

    symbol: str
    adv_inr: float
    median_spread_bps: float


@dataclass(frozen=True, slots=True)
class Rejection:
    """A rejected symbol and the reason code(s) it failed on."""

    symbol: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScreenResult:
    """The screen outcome: eligible symbols and reasoned rejections."""

    eligible: tuple[str, ...]
    rejected: tuple[Rejection, ...]


class LiquidityScreen:
    """Applies liquidity/eligibility thresholds + ESM/T2T exclusion to candidate names."""

    def __init__(self, eligibility: UniverseEligibility) -> None:
        """Build the screen from the universe eligibility thresholds."""
        self._eligibility = eligibility

    def evaluate(self, metrics: LiquidityMetrics, *, is_esm_t2t: bool) -> tuple[str, ...]:
        """Return the rejection reasons for one symbol (empty tuple → eligible)."""
        reasons: list[str] = []
        if metrics.adv_inr < self._eligibility.min_adv_inr:
            reasons.append(REASON_ADV_BELOW_MIN)
        if metrics.median_spread_bps > self._eligibility.max_spread_bps:
            reasons.append(REASON_SPREAD_TOO_WIDE)
        if self._eligibility.exclude_esm_t2t and is_esm_t2t:
            reasons.append(REASON_ESM_T2T_EXCLUDED)
        return tuple(reasons)

    def screen(
        self, metrics: Sequence[LiquidityMetrics], *, esm_t2t: Set[str] = frozenset()
    ) -> ScreenResult:
        """Screen candidate symbols into eligible vs reasoned-rejected.

        Args:
            metrics: Per-symbol liquidity metrics for the candidate universe.
            esm_t2t: Symbols currently flagged ESM/Trade-to-Trade (excluded when the
                eligibility toggle is on). Operator-provided reference data.

        Returns:
            A :class:`ScreenResult` with sorted eligible symbols and the rejections.
        """
        eligible: list[str] = []
        rejected: list[Rejection] = []
        for metric in metrics:
            reasons = self.evaluate(metric, is_esm_t2t=metric.symbol in esm_t2t)
            if reasons:
                rejected.append(Rejection(symbol=metric.symbol, reasons=reasons))
            else:
                eligible.append(metric.symbol)
        _logger.info(
            "liquidity screen applied",
            extra={
                "candidates": len(metrics),
                "eligible": len(eligible),
                "rejected": len(rejected),
            },
        )
        return ScreenResult(eligible=tuple(sorted(eligible)), rejected=tuple(rejected))


def average_daily_value(bars: pd.DataFrame) -> float:
    """Return the average daily traded value (INR) across the trading days in ``bars``.

    Daily value is ``sum(close * volume)`` over the day's bars; ADV is the mean of that
    across the distinct IST trading days present (``0.0`` for an empty frame).

    Raises:
        SchemaError: If ``bars`` is not in the canonical schema.
    """
    frame = serde.ensure_bars_schema(bars)
    if frame.empty:
        return 0.0
    value = frame["close"] * frame["volume"]
    day = frame[serde.TIME_COLUMN].dt.tz_convert(IST).dt.date
    daily_value = value.groupby(day).sum()
    return float(daily_value.mean())
