"""Forward-record live 5-level depth into the research archive (Part VI / P9.1).

Cycle 3b established that historical 5-level depth / microstructure data is **inaccessible at
retail budget** (``FINDINGS.md`` §6) — it is the one feature family that might carry more intraday
signal and cannot be *bought*. The structural answer is to **accrue it forward**: persist the live
``full``-mode depth the P1.2 stream already parses, day over day, so that over months a proprietary
microstructure dataset exists where none could be purchased.

This module is SDK-agnostic — it consumes typed :class:`~quant.core.types.MarketUpdate` /
:class:`~quant.core.types.DepthSnapshot` (the stream's output), never the Kite SDK — and persists
to an immutable, ``symbol/date``-partitioned Parquet archive (the same cold-tier discipline as
:class:`~quant.data.store.parquet.ParquetArchive`). Writes are **idempotent** (a snapshot is keyed
by ``(symbol, timestamp)``; re-recording a day merges and de-duplicates) and **bounded** (the
recorder flushes in fixed batches, so memory never grows without limit). *Accrual is slow by
nature — the value compounds over months.*
"""

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from quant.core.calendar import IST
from quant.core.logging import get_logger
from quant.core.types import DepthLevel, DepthSnapshot, MarketUpdate
from quant.data.recorders.errors import DepthRecorderError

_logger = get_logger(__name__)

#: Hive-style partition layout: ``<root>/symbol=<S>/date=<YYYY-MM-DD>/depth.parquet``.
_SYMBOL_PREFIX = "symbol="
_DATE_PREFIX = "date="
_PARTITION_FILE = "depth.parquet"
_DATE_FORMAT = "%Y-%m-%d"
#: Order-book depth captured per side (NSE redistributable depth is 5 levels).
_LEVELS = 5
#: The snapshot identity column (idempotency key together with ``symbol``).
_TIME_COLUMN = "timestamp"


def depth_snapshot_to_row(snapshot: DepthSnapshot) -> dict[str, object]:
    """Flatten a :class:`DepthSnapshot` into one row: symbol, timestamp, and 5 levels per side.

    Missing levels are filled with ``NaN`` price and ``0`` quantity/orders, so every row has the
    same fixed schema (``bid_px_1..5`` / ``bid_qty_1..5`` / ``bid_ord_1..5`` and ``ask_*``).

    Raises:
        DepthRecorderError: If the snapshot timestamp is tz-naive (point-in-time needs IST).
    """
    if snapshot.timestamp.tzinfo is None:
        raise DepthRecorderError(f"{snapshot.symbol}: depth snapshot timestamp must be tz-aware")
    row: dict[str, object] = {"symbol": snapshot.symbol, _TIME_COLUMN: snapshot.timestamp}
    _fill_side(row, "bid", snapshot.bids)
    _fill_side(row, "ask", snapshot.asks)
    return row


class DepthSnapshotArchive:
    """An immutable, ``symbol/date``-partitioned Parquet archive of flattened depth snapshots.

    Writes accumulate-then-write-once per partition (read existing → merge → de-duplicate by
    timestamp → rewrite), so re-recording a day is idempotent and the partition stays the single
    point-in-time record for that ``symbol/date``.
    """

    def __init__(self, root: str | Path) -> None:
        """Bind the archive to a root directory (created on first write)."""
        self._root = Path(root)

    def write(self, snapshots: Sequence[DepthSnapshot]) -> int:
        """Persist ``snapshots`` to their ``symbol/date`` partitions; return the rows written."""
        if not snapshots:
            return 0
        frame = pd.DataFrame([depth_snapshot_to_row(s) for s in snapshots])
        written = 0
        ist_dates = frame[_TIME_COLUMN].dt.tz_convert(IST).dt.date
        for (symbol, day), group in frame.groupby(["symbol", ist_dates], sort=True):
            written += self._write_partition(
                str(symbol), cast(date, day), group.drop(columns="symbol")
            )
        return written

    def read(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Read recorded depth rows for ``symbol`` over the inclusive IST date range."""
        frames: list[pd.DataFrame] = []
        symbol_dir = self._root / f"{_SYMBOL_PREFIX}{symbol}"
        if not symbol_dir.is_dir():
            return pd.DataFrame()
        for partition in sorted(symbol_dir.glob(f"{_DATE_PREFIX}*")):
            day = _parse_partition_date(partition.name)
            if day is None or not start <= day <= end:
                continue
            file = partition / _PARTITION_FILE
            if file.is_file():
                frames.append(pd.read_parquet(file))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values(_TIME_COLUMN, ignore_index=True)

    def _write_partition(self, symbol: str, day: date, group: pd.DataFrame) -> int:
        """Merge ``group`` into the ``symbol/date`` partition (de-dup by timestamp); return rows."""
        path = (
            self._root / f"{_SYMBOL_PREFIX}{symbol}" / f"{_DATE_PREFIX}{day.strftime(_DATE_FORMAT)}"
        )
        path.mkdir(parents=True, exist_ok=True)
        file = path / _PARTITION_FILE
        merged = group
        if file.is_file():
            merged = pd.concat([pd.read_parquet(file), group], ignore_index=True)
        merged = merged.drop_duplicates(subset=_TIME_COLUMN, keep="last").sort_values(
            _TIME_COLUMN, ignore_index=True
        )
        merged.to_parquet(file, index=False)
        _logger.info(
            "depth archive wrote partition",
            extra={"symbol": symbol, "date": day.isoformat(), "rows": len(merged)},
        )
        return len(merged)


class DepthRecorder:
    """Buffers live :class:`MarketUpdate` depth and flushes it to the archive in bounded batches.

    Memory is bounded by ``batch_size``: once that many snapshots accumulate they are flushed
    automatically. Updates without a depth payload (``ltp``/``quote`` ticks) are ignored. Call
    :meth:`flush` at session end to persist the tail.
    """

    def __init__(self, archive: DepthSnapshotArchive, *, batch_size: int = 1000) -> None:
        """Bind the recorder to its archive sink and the flush batch size (> 0)."""
        if batch_size <= 0:
            raise DepthRecorderError(f"batch_size must be positive, got {batch_size}")
        self._archive = archive
        self._batch_size = batch_size
        self._buffer: list[DepthSnapshot] = []
        self._recorded = 0

    @property
    def recorded(self) -> int:
        """Total snapshots persisted to the archive so far."""
        return self._recorded

    @property
    def buffered(self) -> int:
        """Snapshots held in the buffer, not yet flushed."""
        return len(self._buffer)

    def record(self, update: MarketUpdate) -> None:
        """Buffer one update's depth snapshot (no-op if it carries no order book)."""
        if update.depth is not None:
            self._buffer.append(update.depth)
            if len(self._buffer) >= self._batch_size:
                self.flush()

    def record_all(self, updates: Iterable[MarketUpdate]) -> None:
        """Record every update in ``updates`` (auto-flushing per batch)."""
        for update in updates:
            self.record(update)

    def flush(self) -> int:
        """Persist the buffer to the archive, clear it, and return the rows written."""
        if not self._buffer:
            return 0
        written = self._archive.write(self._buffer)
        self._recorded += written
        self._buffer.clear()
        return written


def _fill_side(row: dict[str, object], side: str, levels: Sequence[DepthLevel]) -> None:
    """Write ``<side>_px/qty/ord_1..5`` into ``row`` (missing levels → NaN price, 0 qty/orders)."""
    for i in range(_LEVELS):
        level = levels[i] if i < len(levels) else None
        row[f"{side}_px_{i + 1}"] = float(level.price) if level else np.nan
        row[f"{side}_qty_{i + 1}"] = int(level.quantity) if level else 0
        row[f"{side}_ord_{i + 1}"] = int(level.orders) if level else 0


def _parse_partition_date(name: str) -> date | None:
    """Parse a ``date=YYYY-MM-DD`` partition directory name, or ``None`` if it does not match."""
    if not name.startswith(_DATE_PREFIX):
        return None
    try:
        return pd.Timestamp(name[len(_DATE_PREFIX) :]).date()
    except ValueError:
        return None
