"""Historical backfill — paginated, resumable multi-year ingest into a ``Repository``.

Deep Dive #1 §1.1/1.2 and the "What I'd build" ``ingest/`` spec: the historical
backfill job, *paginated* to respect the broker's per-request history cap and
*resumable* so a multi-year pull can stop and continue without re-fetching completed
work or duplicating data. It writes through the :class:`~quant.core.interfaces.Repository`
interface (P1.3), so the same job populates the immutable Parquet archive, the
versioned ArcticDB store, or the Redis hot tier with no change.

Why the job is shaped this way:

* **Paginated fetch.** Kite caps the date span of a single ``historical_data``
  request (~60 days for minute candles; §0.2). The job splits ``[start, end]`` into
  day-aligned, non-overlapping ``chunk_days`` windows and fetches each separately. The
  window is configuration (Ground Rule 2), since the cap differs by interval/broker.

* **One write per symbol (contract-faithful).** ``Repository.write_bars`` is *not* a
  guaranteed append across tiers: the Parquet tier appends day-partitions, but the
  ArcticDB tier writes the frame as a whole new *version* and the Redis tier merges a
  bounded window (P1.3). The only behaviour the interface guarantees everywhere is
  "persist this frame as the symbol's data, idempotently, readable back by range". So
  the job accumulates a symbol's chunks into one frame and writes it **once**. That is
  correct on every tier and yields exactly one Arctic version per symbol per run — the
  point-in-time dataset snapshot that versioning exists for.

* **Resumable + no duplication.** A :class:`BackfillCheckpoint` records, per
  ``(symbol, interval)``, the date the backfill has completed *through*. On re-run a
  symbol already complete through the requested ``end`` is skipped entirely (no
  re-fetch); any other symbol is fetched in full and written once. Because that single
  write is idempotent, nothing is duplicated even if the checkpoint is missing or a
  prior run died mid-symbol. Resume granularity is therefore one symbol; finer
  (per-chunk) *durable* resume would need an explicit append method on ``Repository``
  — deferred, tracked.
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from quant.core.calendar import IST
from quant.core.interfaces import BrokerAdapter, Repository
from quant.core.logging import get_logger
from quant.data.ingest.errors import BackfillCheckpointError
from quant.data.store import serde

_logger = get_logger(__name__)


def day_start(day: date) -> datetime:
    """Return the start-of-day instant (00:00:00 IST) for ``day``."""
    return datetime.combine(day, time.min, tzinfo=IST)


def day_end(day: date) -> datetime:
    """Return the end-of-day instant (23:59:59.999999 IST) for ``day``.

    Chunk windows close on end-of-day so every intraday bar of that calendar day
    falls inside exactly one chunk (the partition tiers key on the IST day).
    """
    return datetime.combine(day, time.max, tzinfo=IST)


def iter_chunks(
    start: datetime, end: datetime, chunk_days: int
) -> Iterator[tuple[datetime, datetime]]:
    """Yield day-aligned, non-overlapping ``(chunk_start, chunk_end)`` windows.

    The windows partition ``[start, end]`` by whole IST calendar days, each spanning at
    most ``chunk_days`` days. The first window keeps the caller's exact ``start`` and
    the last keeps the exact ``end``; interior boundaries fall on day edges so no
    calendar day is ever split across two chunks (which would split a day-partition).

    Args:
        start: Inclusive range start (tz-aware).
        end: Inclusive range end (tz-aware).
        chunk_days: Maximum inclusive calendar-day span per window (must be > 0).

    Yields:
        Consecutive ``(chunk_start, chunk_end)`` datetime pairs covering the range.
    """
    if start > end:
        return
    start_day = start.astimezone(IST).date()
    end_day = end.astimezone(IST).date()
    cursor = start_day
    first = True
    while cursor <= end_day:
        last = min(cursor + timedelta(days=chunk_days - 1), end_day)
        chunk_start = start if first else day_start(cursor)
        chunk_end = end if last == end_day else day_end(last)
        yield chunk_start, chunk_end
        first = False
        cursor = last + timedelta(days=1)


@runtime_checkable
class BackfillCheckpoint(Protocol):
    """Records how far a ``(symbol, interval)`` backfill has completed, for resume."""

    def completed_through(self, symbol: str, interval: str) -> date | None:
        """Return the date ``(symbol, interval)`` is backfilled through, or ``None``."""
        ...

    def mark_completed(self, symbol: str, interval: str, through: date) -> None:
        """Record ``(symbol, interval)`` as backfilled through ``through`` (inclusive)."""
        ...


class JsonBackfillCheckpoint:
    """A :class:`BackfillCheckpoint` persisted as a small JSON file.

    The file maps ``"<symbol>:<interval>"`` to the ISO date the backfill has completed
    through. Writes are atomic (temp file then ``replace``) so a crash mid-write cannot
    corrupt the resume state. The state is loaded once on construction and kept in
    memory; each :meth:`mark_completed` flushes the whole (tiny) map.
    """

    def __init__(self, path: str | Path) -> None:
        """Open (or start) the checkpoint at ``path`` (its directory is created on save)."""
        self._path = Path(path)
        self._state: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        """Load existing resume state, or ``{}`` if the file does not exist yet."""
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise BackfillCheckpointError(
                f"backfill checkpoint at {self._path} is unreadable: {exc}. "
                "Fix or delete it (deleting only forces a full re-backfill)."
            ) from exc
        if not isinstance(raw, dict):
            raise BackfillCheckpointError(
                f"backfill checkpoint at {self._path} is not a JSON object."
            )
        return {str(key): str(value) for key, value in raw.items()}

    @staticmethod
    def _key(symbol: str, interval: str) -> str:
        """Compose the per-(symbol, interval) state key."""
        return f"{symbol}:{interval}"

    def completed_through(self, symbol: str, interval: str) -> date | None:
        """Return the stored completion date for ``(symbol, interval)``, or ``None``."""
        value = self._state.get(self._key(symbol, interval))
        return date.fromisoformat(value) if value is not None else None

    def mark_completed(self, symbol: str, interval: str, through: date) -> None:
        """Record completion through ``through`` and atomically flush to disk."""
        self._state[self._key(symbol, interval)] = through.isoformat()
        self._save()

    def _save(self) -> None:
        """Atomically write the state map (temp file then replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, indent=2, sort_keys=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._path)


@dataclass(frozen=True, slots=True)
class SymbolBackfill:
    """The outcome of backfilling one symbol."""

    symbol: str
    interval: str
    bars_written: int
    chunks_fetched: int
    succeeded: bool
    already_complete: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """The aggregate outcome of a backfill run over a set of symbols."""

    results: tuple[SymbolBackfill, ...]

    @property
    def ok(self) -> bool:
        """Whether every symbol succeeded (the run can be reported clean)."""
        return all(result.succeeded for result in self.results)

    @property
    def failed(self) -> tuple[SymbolBackfill, ...]:
        """The symbols whose backfill failed (empty when the run is clean)."""
        return tuple(result for result in self.results if not result.succeeded)

    @property
    def total_bars_written(self) -> int:
        """Total bars written across all symbols in this run."""
        return sum(result.bars_written for result in self.results)


class BackfillJob:
    """Paginated, resumable historical backfill into a :class:`Repository`.

    Collaborators are injected (Ground Rule 1): the :class:`BrokerAdapter` to fetch
    from, the :class:`Repository` to write to, and the :class:`BackfillCheckpoint`
    holding resume state. None require a network or credentials to construct, so the
    job is fully unit-testable with a fake adapter and an in-memory checkpoint.
    """

    def __init__(
        self,
        adapter: BrokerAdapter,
        repository: Repository,
        checkpoint: BackfillCheckpoint,
        *,
        interval: str,
        chunk_days: int,
    ) -> None:
        """Build the job.

        Args:
            adapter: Market-data source (behind :class:`BrokerAdapter`).
            repository: Destination store (behind :class:`Repository`).
            checkpoint: Resume state for ``(symbol, interval)``.
            interval: Candle interval to fetch (validated by the adapter).
            chunk_days: Inclusive calendar-day span per paginated request (> 0).

        Raises:
            ValueError: If ``chunk_days`` is not positive.
        """
        if chunk_days <= 0:
            raise ValueError(f"chunk_days must be positive, got {chunk_days!r}")
        self._adapter = adapter
        self._repository = repository
        self._checkpoint = checkpoint
        self._interval = interval
        self._chunk_days = chunk_days

    def run(self, symbols: Sequence[str], start: datetime, end: datetime) -> BackfillReport:
        """Backfill ``symbols`` over ``[start, end]``, returning a per-symbol report.

        A per-symbol failure (e.g. a transient fetch error) is isolated: it is logged
        at ERROR, recorded in the report as not-succeeded, and the run continues with
        the next symbol — one bad symbol must not abort a long multi-symbol backfill.
        The caller inspects :attr:`BackfillReport.ok` to decide the exit status.

        Args:
            symbols: Trading symbols to backfill.
            start: Inclusive range start (tz-aware; naive raises).
            end: Inclusive range end (tz-aware; naive raises).

        Returns:
            A :class:`BackfillReport` summarising every symbol's outcome.

        Raises:
            ValueError: If ``start``/``end`` are naive or ``start`` is after ``end``.
        """
        _require_aware(start, "start")
        _require_aware(end, "end")
        if start > end:
            raise ValueError(f"start {start.isoformat()} is after end {end.isoformat()}")
        _logger.info(
            "backfill started",
            extra={
                "symbols": len(symbols),
                "interval": self._interval,
                "chunk_days": self._chunk_days,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        results = tuple(self._backfill_symbol(symbol, start, end) for symbol in symbols)
        report = BackfillReport(results)
        _logger.info(
            "backfill finished",
            extra={
                "symbols": len(results),
                "bars_written": report.total_bars_written,
                "failed": len(report.failed),
            },
        )
        return report

    def _backfill_symbol(self, symbol: str, start: datetime, end: datetime) -> SymbolBackfill:
        """Backfill one symbol, isolating any failure into its result."""
        try:
            return self._do_symbol(symbol, start, end)
        except Exception as exc:
            _logger.error(
                "backfill failed for symbol",
                extra={"symbol": symbol, "interval": self._interval, "error": str(exc)},
            )
            return SymbolBackfill(
                symbol=symbol,
                interval=self._interval,
                bars_written=0,
                chunks_fetched=0,
                succeeded=False,
                error=str(exc),
            )

    def _do_symbol(self, symbol: str, start: datetime, end: datetime) -> SymbolBackfill:
        """Fetch, accumulate, and write one symbol; advance its checkpoint."""
        end_day = end.astimezone(IST).date()
        resume = self._checkpoint.completed_through(symbol, self._interval)
        if resume is not None and resume >= end_day:
            _logger.info(
                "backfill skipping completed symbol",
                extra={"symbol": symbol, "interval": self._interval, "through": resume.isoformat()},
            )
            return SymbolBackfill(
                symbol=symbol,
                interval=self._interval,
                bars_written=0,
                chunks_fetched=0,
                succeeded=True,
                already_complete=True,
            )

        # Fetch the full range in paginated chunks, then write once (see module note:
        # the single write is the only tier-agnostic, idempotent way to persist a
        # multi-chunk series). A mid-fetch error propagates without writing or
        # checkpointing, so the symbol is re-fetched in full on the next run.
        chunks = list(iter_chunks(start, end, self._chunk_days))
        frames = [
            self._adapter.fetch_historical(symbol, chunk_start, chunk_end, self._interval)
            for chunk_start, chunk_end in chunks
        ]
        accumulated = serde.concat_bars(frames)
        self._repository.write_bars(symbol, accumulated)
        self._checkpoint.mark_completed(symbol, self._interval, end_day)
        _logger.info(
            "backfill wrote symbol",
            extra={
                "symbol": symbol,
                "interval": self._interval,
                "chunks": len(chunks),
                "bars": len(accumulated),
                "through": end_day.isoformat(),
            },
        )
        return SymbolBackfill(
            symbol=symbol,
            interval=self._interval,
            bars_written=len(accumulated),
            chunks_fetched=len(chunks),
            succeeded=True,
        )


def _require_aware(moment: datetime, label: str) -> None:
    """Raise if ``moment`` is timezone-naive (the system's instants are always IST)."""
    if moment.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware (IST), got naive {moment.isoformat()}")
