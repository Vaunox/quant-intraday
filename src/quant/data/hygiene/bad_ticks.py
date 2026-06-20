"""Bad-tick / outlier filtering (Deep Dive #1 §1.3.4).

*"Exchange feeds contain erroneous prints, zero-volume bars, frozen quotes, and gaps.
Apply sane filters (price within circuit limits, volume >= 0, spread plausibility …) —
but **log every correction, never silently mutate**. A filtered tick that was actually
real is its own form of lookahead if you used future info to decide it was bad."*

So this filter (a) **only uses point-in-time information** — the spike test compares each
bar to the *previous valid* close, never to a future bar — and (b) returns the removed
bars as an explicit, logged :class:`TickCorrection` list rather than mutating in place.
The cleaned frame plus the correction log is the audit trail.

It is idempotent: re-filtering an already-clean frame removes nothing, because every
retained bar was validated against the same predecessor it has in the cleaned series.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from quant.core.config import HygieneConfig
from quant.core.logging import get_logger
from quant.data.store import serde

_logger = get_logger(__name__)


class BadTickReason(str, Enum):
    """Why a bar was rejected as a bad tick."""

    NON_POSITIVE_PRICE = "non_positive_price"  # an OHLC value <= 0
    NEGATIVE_VOLUME = "negative_volume"  # volume < 0
    OHLC_INCONSISTENT = "ohlc_inconsistent"  # high < low, or high/low don't bound open/close
    PRICE_SPIKE = "price_spike"  # close jumped > threshold from the previous valid close


@dataclass(frozen=True, slots=True)
class TickCorrection:
    """One rejected bar and the reason — the audit record of a correction."""

    symbol: str
    timestamp: datetime
    reason: BadTickReason
    detail: str


@dataclass(frozen=True, slots=True)
class BadTickResult:
    """The outcome of filtering a symbol's bars: the clean frame plus the corrections."""

    symbol: str
    clean: pd.DataFrame
    corrections: tuple[TickCorrection, ...]

    @property
    def removed(self) -> int:
        """Number of bars removed as bad ticks."""
        return len(self.corrections)


class BadTickFilter:
    """Removes structurally-invalid and implausible bars, logging every correction."""

    def __init__(self, *, max_move_pct: float) -> None:
        """Build the filter.

        Args:
            max_move_pct: Maximum plausible close-to-close move (percent) from the
                previous valid bar before a bar is flagged as a spike (must be > 0).

        Raises:
            ValueError: If ``max_move_pct`` is not positive.
        """
        if max_move_pct <= 0:
            raise ValueError(f"max_move_pct must be positive, got {max_move_pct!r}")
        self._max_move = max_move_pct

    @classmethod
    def from_config(cls, hygiene: HygieneConfig) -> "BadTickFilter":
        """Build from the hygiene configuration section."""
        return cls(max_move_pct=hygiene.bad_tick_max_move_pct)

    def filter(self, symbol: str, bars: pd.DataFrame) -> BadTickResult:
        """Return ``symbol``'s bars with bad ticks removed, plus the correction log.

        Args:
            symbol: The instrument the bars belong to.
            bars: A canonical-schema bars DataFrame.

        Returns:
            A :class:`BadTickResult` with the cleaned frame (time-sorted) and one
            :class:`TickCorrection` per removed bar (each also logged at WARNING).

        Raises:
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        # Iterate over column lists (not itertuples) so the scalar types are concrete.
        opens = frame["open"].tolist()
        highs = frame["high"].tolist()
        lows = frame["low"].tolist()
        closes = frame["close"].tolist()
        volumes = frame["volume"].tolist()
        timestamps = list(frame[serde.TIME_COLUMN])

        kept: list[int] = []
        corrections: list[TickCorrection] = []
        last_valid_close: float | None = None
        for i in range(len(frame)):
            reason = self._classify(
                opens[i], highs[i], lows[i], closes[i], volumes[i], last_valid_close
            )
            if reason is None:
                kept.append(i)
                last_valid_close = float(closes[i])
                continue
            corrections.append(
                TickCorrection(
                    symbol=symbol,
                    timestamp=timestamps[i],
                    reason=reason,
                    detail=_describe(opens[i], highs[i], lows[i], closes[i], volumes[i]),
                )
            )
            _logger.warning(
                "bad tick removed",
                extra={
                    "symbol": symbol,
                    "timestamp": timestamps[i].isoformat(),
                    "reason": reason.value,
                },
            )

        clean = frame.iloc[kept].reset_index(drop=True)
        return BadTickResult(symbol=symbol, clean=clean, corrections=tuple(corrections))

    def _classify(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        last_valid_close: float | None,
    ) -> BadTickReason | None:
        """Return the bad-tick reason for a bar, or ``None`` if it is valid.

        Structural checks come first (they need no history); the spike check is last and
        only applies once a previous valid close exists (point-in-time, never forward).
        """
        if min(open_, high, low, close) <= 0:
            return BadTickReason.NON_POSITIVE_PRICE
        if volume < 0:
            return BadTickReason.NEGATIVE_VOLUME
        if high < low or high < max(open_, close) or low > min(open_, close):
            return BadTickReason.OHLC_INCONSISTENT
        if last_valid_close is not None:
            move_pct = abs(close / last_valid_close - 1.0) * 100.0
            if move_pct > self._max_move:
                return BadTickReason.PRICE_SPIKE
        return None


def _describe(open_: float, high: float, low: float, close: float, volume: int) -> str:
    """Render a compact OHLCV description for a correction record."""
    return f"O={open_} H={high} L={low} C={close} V={volume}"
