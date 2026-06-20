"""Corporate-action adjustment (Deep Dive #1 §1.3.2).

*"Splits, bonuses, dividends … create artificial price jumps. Maintain an
adjustment-factor table and store both raw and adjusted series. Use adjusted prices for
return/feature computation; raw prices for realistic fill simulation. A 1:5 split misread
as a -80% return will poison a model instantly."*

This module is the **adjusted** half of that split: a pure, deterministic transform from
a raw bars frame to a back-adjusted one. The raw series is untouched (it stays the
immutable archive from P1.4); the caller persists this adjusted output alongside it.

**Back-adjustment convention.** Each action has an ex-date and a multiplicative price
factor applied to every bar *strictly before* that ex-date, so the historical series lines
up with post-ex prices (no artificial jump). For a share-count action (split/bonus) with
``ratio`` = shares-after / shares-before, the price factor is ``1/ratio`` and volume scales
by ``ratio`` (traded value is preserved). For a cash dividend of ``amount`` per share, the
price factor is ``(C - amount) / C`` where ``C`` is the raw close on the last bar before the
ex-date, and volume is unchanged. Multiple actions compound multiplicatively.

Being a pure function of (raw bars, actions) makes the job idempotent in the sense that
matters: re-running it on the same inputs always yields the same adjusted output.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd

from quant.core.calendar import IST
from quant.core.logging import get_logger
from quant.data.hygiene.errors import CorporateActionError
from quant.data.store import serde

_logger = get_logger(__name__)

#: OHLC price columns adjusted by the cumulative price factor.
_PRICE_COLUMNS = ("open", "high", "low", "close")


class CorporateActionType(str, Enum):
    """The price-affecting corporate actions this module adjusts for."""

    SPLIT = "split"  # stock split (face-value subdivision)
    BONUS = "bonus"  # bonus issue (free additional shares)
    DIVIDEND = "dividend"  # cash dividend


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """One corporate action on a symbol, as an adjustment-factor table entry.

    Attributes:
        symbol: The instrument the action applies to.
        ex_date: The ex-date; bars strictly before it are back-adjusted.
        action_type: Split, bonus, or dividend.
        ratio: Shares-after / shares-before for split/bonus (e.g. ``5.0`` for a 1:5
            split, ``2.0`` for a 1:1 bonus). Unused for dividends.
        amount: Cash dividend per share (only for ``DIVIDEND``).

    Raises:
        CorporateActionError: If the ratio or dividend amount is invalid.
    """

    symbol: str
    ex_date: date
    action_type: CorporateActionType
    ratio: float = 1.0
    amount: float = 0.0

    def __post_init__(self) -> None:
        """Validate the action at construction (fail loud — Ground Rule 7)."""
        if self.action_type is CorporateActionType.DIVIDEND:
            if self.amount <= 0:
                raise CorporateActionError(
                    f"{self.symbol} dividend on {self.ex_date} must have a positive amount, "
                    f"got {self.amount!r}"
                )
        elif self.ratio <= 0:
            raise CorporateActionError(
                f"{self.symbol} {self.action_type.value} on {self.ex_date} must have a "
                f"positive ratio, got {self.ratio!r}"
            )

    def price_factor(self, reference_close: float) -> float:
        """Return the multiplicative factor applied to pre-ex-date prices.

        Args:
            reference_close: Raw close on the last bar before the ex-date (only used
                for dividends; ignored for split/bonus).

        Raises:
            CorporateActionError: If a dividend is not smaller than the reference close
                (it would drive the adjusted price non-positive).
        """
        if self.action_type is CorporateActionType.DIVIDEND:
            if self.amount >= reference_close:
                raise CorporateActionError(
                    f"{self.symbol} dividend {self.amount} on {self.ex_date} is not below the "
                    f"reference close {reference_close}; cannot adjust."
                )
            return (reference_close - self.amount) / reference_close
        return 1.0 / self.ratio

    @property
    def volume_factor(self) -> float:
        """Return the multiplicative factor applied to pre-ex-date volumes."""
        if self.action_type is CorporateActionType.DIVIDEND:
            return 1.0
        return self.ratio


class CorporateActionAdjuster:
    """Back-adjusts a raw bars frame for a symbol's corporate actions (pure transform)."""

    def __init__(self, actions: Sequence[CorporateAction]) -> None:
        """Build the adjuster over an adjustment-factor table (any symbols)."""
        self._actions = tuple(sorted(actions, key=lambda action: action.ex_date))

    def adjust(self, symbol: str, raw_bars: pd.DataFrame) -> pd.DataFrame:
        """Return ``symbol``'s bars back-adjusted for its corporate actions.

        Bars strictly before each ex-date are scaled by the compounded price/volume
        factors; bars on/after the latest ex-date are unchanged. With no actions for the
        symbol the input is returned unchanged (schema-validated and time-sorted).

        Args:
            symbol: The instrument whose actions to apply.
            raw_bars: A canonical-schema raw bars DataFrame.

        Returns:
            A canonical-schema adjusted bars DataFrame (raw is never mutated).

        Raises:
            SchemaError: If ``raw_bars`` is not in the canonical schema.
            CorporateActionError: If a dividend is not below its reference close.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(raw_bars))
        actions = [action for action in self._actions if action.symbol == symbol]
        if frame.empty or not actions:
            return frame

        bar_dates = frame[serde.TIME_COLUMN].dt.tz_convert(IST).dt.date
        raw_close = frame["close"]
        cum_price = pd.Series(1.0, index=frame.index)
        cum_volume = pd.Series(1.0, index=frame.index)
        applied = 0
        for action in actions:
            before_ex = bar_dates < action.ex_date
            if not before_ex.any():
                # No history before this ex-date (e.g. action predates the archive).
                continue
            reference_close = float(raw_close[before_ex].iloc[-1])
            cum_price.loc[before_ex] *= action.price_factor(reference_close)
            cum_volume.loc[before_ex] *= action.volume_factor
            applied += 1

        if applied == 0:
            # Every action's ex-date predates the archive — nothing to adjust; return the
            # frame unchanged (and untouched in dtype) rather than a 1.0-scaled copy.
            return frame

        adjusted = frame.copy()
        for column in _PRICE_COLUMNS:
            adjusted[column] = frame[column] * cum_price
        adjusted["volume"] = (frame["volume"] * cum_volume).round().astype("int64")
        _logger.info(
            "corporate-action adjusted",
            extra={"symbol": symbol, "actions_applied": applied, "bars": len(frame)},
        )
        return adjusted
