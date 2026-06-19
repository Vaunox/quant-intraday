"""``ParquetArchive`` — the immutable raw archive tier (cold storage).

Deep Dive #1 §1.2: *"Partition raw archives by ``symbol/date`` and keep them immutable
and versioned — you never overwrite history; corrections become new versions."* This
is the cold tier of the three-tier design and the system's point-in-time source of
truth: once a ``symbol/date`` partition is written it cannot be silently changed.

Layout on disk (Hive-style partitions, one Parquet file per trading day)::

    <root>/symbol=<SYMBOL>/date=<YYYY-MM-DD>/bars.parquet

* ``write_bars`` is **idempotent** for identical data and **immutable** otherwise:
  re-writing the same bars for a day is a no-op; writing *different* bars for an
  already-archived day raises :class:`ImmutableArchiveError`.
* Partition dates are the bar's **IST** calendar date, so a trading session maps to a
  single partition regardless of the caller's timezone.

Implements :class:`~quant.core.interfaces.Repository`. Uses only pandas + pyarrow, so
it is real (not faked) and fully round-trip tested.
"""

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quant.core.calendar import IST
from quant.core.config import StorageConfig
from quant.core.logging import get_logger
from quant.data.store import serde
from quant.data.store.errors import ImmutableArchiveError

_logger = get_logger(__name__)

#: Prefixes for the Hive-style partition directory names.
_SYMBOL_PREFIX = "symbol="
_DATE_PREFIX = "date="
#: The single Parquet file inside each ``symbol/date`` partition.
_PARTITION_FILE = "bars.parquet"
#: Partition-date format (sorts lexicographically in calendar order).
_DATE_FORMAT = "%Y-%m-%d"


class ParquetArchive:
    """Immutable, ``symbol/date``-partitioned raw bars archive (a ``Repository``)."""

    def __init__(self, root: str | Path) -> None:
        """Build the archive rooted at ``root`` (created on first write)."""
        self._root = Path(root)

    # ------------------------------------------------------------------ writing
    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        """Archive ``bars`` for ``symbol``, one immutable file per IST trading day.

        Idempotent for identical data; raises for a conflicting overwrite.

        Args:
            symbol: The instrument symbol the bars belong to.
            bars: A canonical-schema bars DataFrame (may span multiple days).

        Raises:
            SchemaError: If ``bars`` is not in the canonical schema.
            ImmutableArchiveError: If a day already holds *different* bars.
        """
        frame = serde.ensure_bars_schema(bars)
        if frame.empty:
            _logger.debug("parquet archive: nothing to write", extra={"symbol": symbol})
            return
        for day, group in self._partition_by_day(frame):
            self._write_partition(symbol, day, group)

    def _write_partition(self, symbol: str, day: date, group: pd.DataFrame) -> None:
        """Write a single ``symbol/date`` partition, enforcing immutability."""
        path = self._partition_path(symbol, day)
        new_frame = serde.from_parquet_bytes(serde.to_parquet_bytes(group))
        if path.exists():
            existing = serde.from_parquet_bytes(path.read_bytes())
            if serde.frames_equal(existing, new_frame):
                _logger.debug(
                    "parquet archive: identical partition exists, skipping",
                    extra={"symbol": symbol, "date": day.isoformat(), "rows": len(group)},
                )
                return
            raise ImmutableArchiveError(
                f"refusing to overwrite immutable archive for {symbol} on "
                f"{day.isoformat()} with different data ({len(existing)} existing vs "
                f"{len(group)} new rows); corrections belong in the versioned store."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then atomically replace, so a crash mid-write can never
        # leave a half-written partition that would read as corrupt history.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(serde.to_parquet_bytes(group))
        tmp.replace(path)
        _logger.info(
            "parquet archive: wrote partition",
            extra={"symbol": symbol, "date": day.isoformat(), "rows": len(group)},
        )

    @staticmethod
    def _partition_by_day(frame: pd.DataFrame) -> list[tuple[date, pd.DataFrame]]:
        """Split a (possibly multi-day) frame into ``(IST date, sub-frame)`` groups."""
        ist_dates = frame[serde.TIME_COLUMN].dt.tz_convert(IST).dt.date
        return [(day, group) for day, group in frame.groupby(ist_dates, sort=True)]

    # ------------------------------------------------------------------ reading
    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Read archived bars for ``symbol`` within ``[start, end]`` (inclusive), in time order.

        Unknown symbols and empty ranges return a well-typed empty frame.
        """
        symbol_dir = self._root / f"{_SYMBOL_PREFIX}{symbol}"
        if not symbol_dir.is_dir():
            return serde.empty_bars_frame()
        start_day = start.astimezone(IST).date()
        end_day = end.astimezone(IST).date()
        frames = [
            serde.from_parquet_bytes((part / _PARTITION_FILE).read_bytes())
            for part, part_day in self._iter_partitions(symbol_dir)
            if start_day <= part_day <= end_day
        ]
        return serde.restrict_to_range(serde.concat_bars(frames), start, end)

    def list_symbols(self) -> Sequence[str]:
        """Return the symbols held in the archive, sorted."""
        if not self._root.is_dir():
            return []
        return sorted(
            entry.name[len(_SYMBOL_PREFIX) :]
            for entry in self._root.iterdir()
            if entry.is_dir() and entry.name.startswith(_SYMBOL_PREFIX)
        )

    # ------------------------------------------------------------------ helpers
    def _partition_path(self, symbol: str, day: date) -> Path:
        """Path to the Parquet file for one ``symbol/date`` partition."""
        return (
            self._root
            / f"{_SYMBOL_PREFIX}{symbol}"
            / f"{_DATE_PREFIX}{day.strftime(_DATE_FORMAT)}"
            / _PARTITION_FILE
        )

    @staticmethod
    def _iter_partitions(symbol_dir: Path) -> list[tuple[Path, date]]:
        """Yield ``(partition dir, date)`` for each valid ``date=`` partition present."""
        partitions: list[tuple[Path, date]] = []
        for entry in symbol_dir.iterdir():
            if not (entry.is_dir() and entry.name.startswith(_DATE_PREFIX)):
                continue
            if not (entry / _PARTITION_FILE).is_file():
                continue
            day = datetime.strptime(entry.name[len(_DATE_PREFIX) :], _DATE_FORMAT).date()
            partitions.append((entry, day))
        return partitions


def create_parquet_archive(storage: StorageConfig) -> ParquetArchive:
    """Build a :class:`ParquetArchive` from the storage configuration."""
    return ParquetArchive(storage.parquet_path)
