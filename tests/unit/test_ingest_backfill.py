"""Tests for the historical backfill job (P1.4).

Cover the acceptance criteria directly: paginates a multi-chunk range, backfills a
small universe, resumes after an interruption without duplication, and writes
versioned data (one Arctic version per symbol). The job is exercised against the real
``ParquetArchive`` (the canonical immutable target) and a fake-library
``ArcticRepository`` (the versioning proof), proving it is repository-agnostic.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from quant.core.interfaces import BrokerAdapter, Repository
from quant.data.ingest.backfill import (
    BackfillCheckpoint,
    BackfillJob,
    JsonBackfillCheckpoint,
    SymbolBackfill,
    day_end,
    day_start,
    iter_chunks,
)
from quant.data.ingest.errors import BackfillCheckpointError
from quant.data.store.arctic import ArcticRepository
from quant.data.store.parquet import ParquetArchive
from tests.unit.ingest_fakes import IST, FakeHistoricalAdapter, InMemoryBackfillCheckpoint
from tests.unit.store_fakes import FakeArcticLibrary

INTERVAL = "minute"
START = day_start(date(2024, 1, 1))
END = day_end(date(2024, 1, 5))  # 5 calendar days
BARS_PER_DAY = 3
EXPECTED_BARS = 5 * BARS_PER_DAY  # 15


def _read_all(repo: Repository, symbol: str) -> "list[datetime]":
    """Return all stored timestamps for ``symbol`` over the test range, in order."""
    frame = repo.read_bars(symbol, START, END)
    return list(frame["timestamp"])


# --------------------------------------------------------------- pure chunking


def test_iter_chunks_partitions_range_day_aligned() -> None:
    chunks = list(iter_chunks(START, END, 2))
    assert chunks == [
        (START, day_end(date(2024, 1, 2))),
        (day_start(date(2024, 1, 3)), day_end(date(2024, 1, 4))),
        (day_start(date(2024, 1, 5)), END),
    ]
    # First chunk keeps the exact start; last keeps the exact end (no clipping).
    assert chunks[0][0] == START
    assert chunks[-1][1] == END


def test_iter_chunks_single_window_when_range_fits() -> None:
    assert list(iter_chunks(START, END, 60)) == [(START, END)]


def test_iter_chunks_per_day_when_chunk_is_one() -> None:
    chunks = list(iter_chunks(START, END, 1))
    assert len(chunks) == 5
    assert all(start.date() == end.date() for start, end in chunks)


def test_iter_chunks_empty_when_start_after_end() -> None:
    assert list(iter_chunks(END, START, 5)) == []


def test_day_helpers_are_ist_boundaries() -> None:
    assert day_start(date(2024, 1, 1)) == datetime(2024, 1, 1, 0, 0, tzinfo=IST)
    assert day_end(date(2024, 1, 1)).hour == 23
    assert day_end(date(2024, 1, 1)).date() == date(2024, 1, 1)


# ------------------------------------------------------------- type conformance


def test_fakes_satisfy_their_protocols() -> None:
    assert isinstance(FakeHistoricalAdapter(), BrokerAdapter)
    assert isinstance(InMemoryBackfillCheckpoint(), BackfillCheckpoint)
    assert isinstance(JsonBackfillCheckpoint("x.json"), BackfillCheckpoint)


# ------------------------------------------------------------- basic + paginate


def test_single_chunk_backfill_writes_and_checkpoints(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    repo = ParquetArchive(tmp_path)
    checkpoint = InMemoryBackfillCheckpoint()
    job = BackfillJob(adapter, repo, checkpoint, interval=INTERVAL, chunk_days=60)

    report = job.run(["RELIANCE"], START, END)

    assert report.ok
    assert report.total_bars_written == EXPECTED_BARS
    assert len(adapter.calls_for("RELIANCE")) == 1  # whole range fits one request
    assert checkpoint.completed_through("RELIANCE", INTERVAL) == date(2024, 1, 5)
    assert len(_read_all(repo, "RELIANCE")) == EXPECTED_BARS


def test_pagination_splits_into_chunk_windows(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    repo = ParquetArchive(tmp_path)
    job = BackfillJob(adapter, repo, InMemoryBackfillCheckpoint(), interval=INTERVAL, chunk_days=2)

    report = job.run(["RELIANCE"], START, END)

    calls = adapter.calls_for("RELIANCE")
    assert len(calls) == 3  # [1-2], [3-4], [5]
    assert calls[0]["start"] == START
    assert calls[0]["end"] == day_end(date(2024, 1, 2))
    assert calls[-1]["end"] == END
    # All chunks land exactly once: full coverage, no duplicates.
    stamps = _read_all(repo, "RELIANCE")
    assert len(stamps) == EXPECTED_BARS
    assert len(set(stamps)) == EXPECTED_BARS
    assert report.results[0].chunks_fetched == 3


def test_backfills_a_small_universe(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    repo = ParquetArchive(tmp_path)
    job = BackfillJob(adapter, repo, InMemoryBackfillCheckpoint(), interval=INTERVAL, chunk_days=2)

    report = job.run(["RELIANCE", "HDFCBANK", "INFY"], START, END)

    assert report.ok
    assert report.total_bars_written == 3 * EXPECTED_BARS
    assert sorted(repo.list_symbols()) == ["HDFCBANK", "INFY", "RELIANCE"]


# --------------------------------------------------------- resume / idempotency


def test_resumes_after_interruption_without_duplication(tmp_path: Path) -> None:
    """One symbol fails; a re-run completes it and re-fetches nothing already done."""
    repo = ParquetArchive(tmp_path)
    checkpoint = InMemoryBackfillCheckpoint()
    universe = ["RELIANCE", "HDFCBANK", "ICICIBANK"]

    # Run 1: ICICIBANK's fetch fails -> isolated; the other two complete.
    failing = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY, raise_on_symbol="ICICIBANK")
    report1 = BackfillJob(failing, repo, checkpoint, interval=INTERVAL, chunk_days=2).run(
        universe, START, END
    )

    assert not report1.ok
    assert [r.symbol for r in report1.failed] == ["ICICIBANK"]
    assert checkpoint.completed_through("RELIANCE", INTERVAL) == date(2024, 1, 5)
    assert checkpoint.completed_through("ICICIBANK", INTERVAL) is None

    # Run 2 (interruption cleared): completed symbols are skipped, not re-fetched.
    healed = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    report2 = BackfillJob(healed, repo, checkpoint, interval=INTERVAL, chunk_days=2).run(
        universe, START, END
    )

    assert report2.ok
    assert healed.calls_for("RELIANCE") == []  # already complete -> no re-fetch
    assert healed.calls_for("HDFCBANK") == []
    assert len(healed.calls_for("ICICIBANK")) == 3  # the unfinished symbol is fetched
    assert {r.symbol for r in report2.results if r.already_complete} == {"RELIANCE", "HDFCBANK"}

    # Final state: every symbol present exactly once, no duplicated bars.
    for symbol in universe:
        stamps = _read_all(repo, symbol)
        assert len(stamps) == EXPECTED_BARS
        assert len(set(stamps)) == EXPECTED_BARS


def test_full_rerun_is_idempotent_noop(tmp_path: Path) -> None:
    repo = ParquetArchive(tmp_path)
    checkpoint = InMemoryBackfillCheckpoint()
    first = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    BackfillJob(first, repo, checkpoint, interval=INTERVAL, chunk_days=2).run(
        ["RELIANCE"], START, END
    )

    second = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    report = BackfillJob(second, repo, checkpoint, interval=INTERVAL, chunk_days=2).run(
        ["RELIANCE"], START, END
    )

    assert report.ok
    assert report.results[0].already_complete
    assert second.calls == []  # nothing re-fetched
    assert len(_read_all(repo, "RELIANCE")) == EXPECTED_BARS


def test_resume_persists_across_checkpoint_instances(tmp_path: Path) -> None:
    """A fresh JsonBackfillCheckpoint (process restart) still resumes from disk."""
    repo = ParquetArchive(tmp_path / "pq")
    cp_path = tmp_path / "backfill_checkpoint.json"

    first = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    BackfillJob(first, repo, JsonBackfillCheckpoint(cp_path), interval=INTERVAL, chunk_days=2).run(
        ["RELIANCE"], START, END
    )
    assert cp_path.is_file()

    # New checkpoint object reads the persisted state -> the symbol is skipped.
    second = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    report = BackfillJob(
        second, repo, JsonBackfillCheckpoint(cp_path), interval=INTERVAL, chunk_days=2
    ).run(["RELIANCE"], START, END)

    assert report.results[0].already_complete
    assert second.calls == []


# ------------------------------------------------------------- versioned writes


def test_writes_versioned_data_one_version_per_symbol() -> None:
    library = FakeArcticLibrary()
    repo = ArcticRepository(library)
    checkpoint = InMemoryBackfillCheckpoint()
    job = BackfillJob(
        FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY),
        repo,
        checkpoint,
        interval=INTERVAL,
        chunk_days=2,
    )

    job.run(["RELIANCE"], START, END)

    # One accumulated write -> exactly one version holding the full series.
    assert repo.list_versions("RELIANCE") == [0]
    assert len(repo.read_bars("RELIANCE", START, END)) == EXPECTED_BARS


def test_extending_end_creates_a_new_version() -> None:
    library = FakeArcticLibrary()
    repo = ArcticRepository(library)
    checkpoint = InMemoryBackfillCheckpoint()

    BackfillJob(
        FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY),
        repo,
        checkpoint,
        interval=INTERVAL,
        chunk_days=60,
    ).run(["RELIANCE"], START, END)

    extended_end = day_end(date(2024, 1, 8))  # +3 days of history
    BackfillJob(
        FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY),
        repo,
        checkpoint,
        interval=INTERVAL,
        chunk_days=60,
    ).run(["RELIANCE"], START, extended_end)

    assert repo.list_versions("RELIANCE") == [0, 1]  # a second, extended version
    assert len(repo.read_bars("RELIANCE", START, extended_end)) == 8 * BARS_PER_DAY


# --------------------------------------------------------------- edge handling


def test_symbol_with_no_data_is_marked_complete(tmp_path: Path) -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=0)  # generates nothing
    repo = ParquetArchive(tmp_path)
    checkpoint = InMemoryBackfillCheckpoint()
    job = BackfillJob(adapter, repo, checkpoint, interval=INTERVAL, chunk_days=2)

    report = job.run(["RELIANCE"], START, END)

    assert report.ok
    assert report.results[0].bars_written == 0
    assert checkpoint.completed_through("RELIANCE", INTERVAL) == date(2024, 1, 5)
    assert list(repo.list_symbols()) == []  # nothing written, but progress recorded


def test_already_complete_symbol_short_circuits_before_fetch() -> None:
    adapter = FakeHistoricalAdapter(bars_per_day=BARS_PER_DAY)
    checkpoint = InMemoryBackfillCheckpoint()
    checkpoint.mark_completed("RELIANCE", INTERVAL, date(2024, 1, 31))  # already past END
    repo = ArcticRepository(FakeArcticLibrary())
    job = BackfillJob(adapter, repo, checkpoint, interval=INTERVAL, chunk_days=2)

    result = job.run(["RELIANCE"], START, END).results[0]

    assert result == SymbolBackfill(
        "RELIANCE", INTERVAL, 0, 0, succeeded=True, already_complete=True
    )
    assert adapter.calls == []


# ----------------------------------------------------------- input validation


def test_non_positive_chunk_days_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_days"):
        BackfillJob(
            FakeHistoricalAdapter(),
            ParquetArchive("unused"),
            InMemoryBackfillCheckpoint(),
            interval=INTERVAL,
            chunk_days=0,
        )


def test_naive_bounds_rejected(tmp_path: Path) -> None:
    job = BackfillJob(
        FakeHistoricalAdapter(),
        ParquetArchive(tmp_path),
        InMemoryBackfillCheckpoint(),
        interval=INTERVAL,
        chunk_days=2,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        job.run(["RELIANCE"], datetime(2024, 1, 1), END)


def test_start_after_end_rejected(tmp_path: Path) -> None:
    job = BackfillJob(
        FakeHistoricalAdapter(),
        ParquetArchive(tmp_path),
        InMemoryBackfillCheckpoint(),
        interval=INTERVAL,
        chunk_days=2,
    )
    with pytest.raises(ValueError, match="after end"):
        job.run(["RELIANCE"], END, START)


# --------------------------------------------------------- JSON checkpoint unit


def test_json_checkpoint_roundtrip_and_atomic(tmp_path: Path) -> None:
    cp = JsonBackfillCheckpoint(tmp_path / "cp.json")
    assert cp.completed_through("RELIANCE", INTERVAL) is None
    cp.mark_completed("RELIANCE", INTERVAL, date(2024, 1, 5))
    assert cp.completed_through("RELIANCE", INTERVAL) == date(2024, 1, 5)
    # Persisted and re-readable by a fresh instance; no temp file left behind.
    assert JsonBackfillCheckpoint(tmp_path / "cp.json").completed_through(
        "RELIANCE", INTERVAL
    ) == date(2024, 1, 5)
    assert list(tmp_path.glob("*.tmp")) == []


def test_json_checkpoint_keys_by_symbol_and_interval(tmp_path: Path) -> None:
    cp = JsonBackfillCheckpoint(tmp_path / "cp.json")
    cp.mark_completed("RELIANCE", "minute", date(2024, 1, 5))
    cp.mark_completed("RELIANCE", "day", date(2024, 1, 9))
    assert cp.completed_through("RELIANCE", "minute") == date(2024, 1, 5)
    assert cp.completed_through("RELIANCE", "day") == date(2024, 1, 9)


def test_json_checkpoint_rejects_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(BackfillCheckpointError, match="unreadable"):
        JsonBackfillCheckpoint(path)


def test_json_checkpoint_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "cp.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(BackfillCheckpointError, match="not a JSON object"):
        JsonBackfillCheckpoint(path)
