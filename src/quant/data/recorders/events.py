"""Systematically record earnings surprise -> reaction -> drift events (Part VI / P9.2).

Accrues, quarter over quarter, the dataset the post-earnings-announcement-drift study (P7.3) needs:
for each earnings event, the **surprise** (actual vs estimate), the **immediate reaction** (the
announcement-window return), and the subsequent **drift** (the PEAD window return). Built on the
P1.3 archive (``Repository``) — the recorder reads the surrounding bars and computes the three
windows point-in-time; the earnings **events** themselves come from an injected source (an
earnings-calendar / surprise feed), so the recorder is testable with no external feed and judges
the mechanism the moment a feed is supplied.

The schema (:class:`EventReactionRecord`) is exactly what a PEAD ``StrategySpec`` consumes: sort on
``surprise``, trade the ``drift_return`` window. *Accrual is slow by nature — one earnings season
at a time.*
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from quant.core.interfaces import Repository
from quant.core.logging import get_logger
from quant.data.recorders.errors import EventRecorderError

_logger = get_logger(__name__)

#: Calendar-day padding around an event so the bar window spans enough trading days.
_DAY_PADDING = 10
#: Trading days per calendar day (rough), to size the read window from the trading-day horizons.
_CAL_PER_TRADING_DAY = 1.6
_TIME_COLUMN = "timestamp"
_STORE_FILE = "event_reactions.parquet"


@dataclass(frozen=True, slots=True)
class EarningsEvent:
    """One earnings announcement: when, and the actual vs the consensus estimate.

    ``surprise`` is the standardized surprise ``(actual - estimate) / |estimate|`` — the sort key
    of the PEAD strategy. ``event_time`` is the announcement instant (tz-aware IST).
    """

    symbol: str
    event_time: datetime
    actual: float
    estimate: float

    @property
    def surprise(self) -> float:
        """The standardized earnings surprise ``(actual - estimate) / |estimate|``."""
        if self.estimate == 0.0:
            return float(np.sign(self.actual - self.estimate))  # undefined scale → direction only
        return (self.actual - self.estimate) / abs(self.estimate)


@dataclass(frozen=True, slots=True)
class EventReactionRecord:
    """One recorded earnings event's surprise + the three return windows (the PEAD substrate)."""

    symbol: str
    event_time: datetime
    surprise: float
    pre_return: float  # return over the ``pre_days`` before the announcement (run-up control)
    reaction_return: float  # return over the ``reaction_days`` announcement window
    drift_return: float  # return over the ``drift_days`` PEAD window after the reaction


class EventReactionRecorder:
    """Computes :class:`EventReactionRecord`s for earnings events from the bars archive (P9.2)."""

    def __init__(
        self,
        repository: Repository,
        *,
        pre_days: int = 5,
        reaction_days: int = 1,
        drift_days: int = 20,
    ) -> None:
        """Bind the recorder to the bars store and the (trading-day) window horizons.

        Raises:
            EventRecorderError: If any horizon is non-positive.
        """
        if pre_days <= 0 or reaction_days <= 0 or drift_days <= 0:
            raise EventRecorderError("pre_days / reaction_days / drift_days must all be positive")
        self._repo = repository
        self._pre = pre_days
        self._reaction = reaction_days
        self._drift = drift_days

    def record(self, events: Sequence[EarningsEvent]) -> list[EventReactionRecord]:
        """Return a record per event whose surrounding bars cover all three windows.

        Events without enough trading-day history around the announcement are skipped (logged), so
        an incomplete feed degrades gracefully rather than fabricating a return.
        """
        records: list[EventReactionRecord] = []
        for event in events:
            record = self._record_one(event)
            if record is not None:
                records.append(record)
        _logger.info(
            "event-reaction recorder",
            extra={"events": len(events), "recorded": len(records)},
        )
        return records

    def _record_one(self, event: EarningsEvent) -> EventReactionRecord | None:
        """Compute one event's windows, or ``None`` if the bars do not cover them."""
        horizon = self._reaction + self._drift
        pad_before = timedelta(days=int(self._pre * _CAL_PER_TRADING_DAY) + _DAY_PADDING)
        pad_after = timedelta(days=int(horizon * _CAL_PER_TRADING_DAY) + _DAY_PADDING)
        bars = self._repo.read_bars(
            event.symbol, event.event_time - pad_before, event.event_time + pad_after
        )
        if bars.empty:
            return None
        bars = bars.sort_values(_TIME_COLUMN, ignore_index=True)
        times = bars[_TIME_COLUMN]
        closes = bars["close"].to_numpy(dtype="float64")
        # Anchor = the last close at/before the announcement (the pre-announcement price).
        anchor = int(times.searchsorted(pd.Timestamp(event.event_time), side="right")) - 1
        pre_i = anchor - self._pre
        react_i = anchor + self._reaction
        drift_i = react_i + self._drift
        if pre_i < 0 or drift_i >= closes.shape[0] or closes[anchor] <= 0.0:
            return None
        return EventReactionRecord(
            symbol=event.symbol,
            event_time=event.event_time,
            surprise=event.surprise,
            pre_return=_ret(closes[pre_i], closes[anchor]),
            reaction_return=_ret(closes[anchor], closes[react_i]),
            drift_return=_ret(closes[react_i], closes[drift_i]),
        )


class ParquetEventReactionStore:
    """A single-table Parquet store of :class:`EventReactionRecord`s (research-queryable)."""

    def __init__(self, root: str | Path) -> None:
        """Bind the store to a root directory (created on first write)."""
        self._root = Path(root)

    def write(self, records: Sequence[EventReactionRecord]) -> int:
        """Merge ``records`` (de-dup by ``(symbol, event_time)``); return the total row count."""
        if not records:
            return self._row_count()
        frame = pd.DataFrame([_record_to_row(r) for r in records])
        self._root.mkdir(parents=True, exist_ok=True)
        file = self._root / _STORE_FILE
        if file.is_file():
            frame = pd.concat([pd.read_parquet(file), frame], ignore_index=True)
        frame = frame.drop_duplicates(subset=["symbol", "event_time"], keep="last").sort_values(
            "event_time", ignore_index=True
        )
        frame.to_parquet(file, index=False)
        _logger.info("event-reaction store wrote", extra={"rows": len(frame)})
        return len(frame)

    def read(self) -> pd.DataFrame:
        """Read the full event-reaction table (empty frame if nothing recorded yet)."""
        file = self._root / _STORE_FILE
        return pd.read_parquet(file) if file.is_file() else pd.DataFrame()

    def _row_count(self) -> int:
        """Current row count (0 if the store does not exist)."""
        file = self._root / _STORE_FILE
        return len(pd.read_parquet(file)) if file.is_file() else 0


def _ret(start: float, end: float) -> float:
    """Simple return ``end/start - 1`` (start is guaranteed positive by the caller)."""
    return float(end) / float(start) - 1.0


def _record_to_row(record: EventReactionRecord) -> dict[str, object]:
    """Flatten a record into a Parquet row."""
    return {
        "symbol": record.symbol,
        "event_time": record.event_time,
        "surprise": record.surprise,
        "pre_return": record.pre_return,
        "reaction_return": record.reaction_return,
        "drift_return": record.drift_return,
    }
