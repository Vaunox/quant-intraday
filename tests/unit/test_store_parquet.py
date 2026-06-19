"""Tests for ParquetArchive — the immutable, symbol/date-partitioned raw tier (P1.3)."""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant.core.config import load_config
from quant.core.frames import BAR_COLUMNS
from quant.core.interfaces import Repository
from quant.data.store.errors import ImmutableArchiveError, SchemaError
from quant.data.store.parquet import ParquetArchive, create_parquet_archive
from tests.unit.store_fakes import IST, sample_bars

DAY1 = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
DAY2 = datetime(2026, 6, 19, 9, 15, tzinfo=IST)
DAY3 = datetime(2026, 6, 22, 9, 15, tzinfo=IST)
WIDE_END = DAY3 + timedelta(days=1)


def test_is_a_repository(tmp_path: Path) -> None:
    assert isinstance(ParquetArchive(tmp_path), Repository)


def test_write_read_roundtrip_is_exact(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    bars = sample_bars("RELIANCE", DAY1, 5)
    archive.write_bars("RELIANCE", bars)
    result = archive.read_bars("RELIANCE", DAY1, DAY1 + timedelta(hours=1))
    pd.testing.assert_frame_equal(result, bars)


def test_partition_layout_on_disk(tmp_path: Path) -> None:
    ParquetArchive(tmp_path).write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 2))
    expected = tmp_path / "symbol=RELIANCE" / "date=2026-06-18" / "bars.parquet"
    assert expected.is_file()
    # The atomic temp file must not survive a successful write.
    assert list(tmp_path.rglob("*.tmp")) == []


def test_multi_day_write_splits_into_partitions(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    bars = pd.concat([sample_bars("RELIANCE", DAY1, 3), sample_bars("RELIANCE", DAY2, 2)])
    archive.write_bars("RELIANCE", bars)
    partitions = sorted(p.name for p in (tmp_path / "symbol=RELIANCE").iterdir())
    assert partitions == ["date=2026-06-18", "date=2026-06-19"]
    assert len(archive.read_bars("RELIANCE", DAY1, WIDE_END)) == 5


def test_identical_rewrite_is_idempotent(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    bars = sample_bars("RELIANCE", DAY1, 3)
    archive.write_bars("RELIANCE", bars)
    archive.write_bars("RELIANCE", bars)  # must not raise
    assert len(archive.read_bars("RELIANCE", DAY1, WIDE_END)) == 3


def test_conflicting_overwrite_raises(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    with pytest.raises(ImmutableArchiveError, match="2026-06-18"):
        archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3, price=999.0))


def test_partial_multiday_write_skips_existing_and_adds_new(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    # Re-write day 1 (identical, skipped) together with a new day 2 (added).
    combined = pd.concat([sample_bars("RELIANCE", DAY1, 3), sample_bars("RELIANCE", DAY2, 4)])
    archive.write_bars("RELIANCE", combined)
    assert len(archive.read_bars("RELIANCE", DAY1, WIDE_END)) == 7


def test_range_filter_excludes_out_of_range_days(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    for day, n in ((DAY1, 3), (DAY2, 4), (DAY3, 2)):
        archive.write_bars("RELIANCE", sample_bars("RELIANCE", day, n))
    only_day2 = archive.read_bars("RELIANCE", DAY2, DAY2 + timedelta(hours=1))
    assert len(only_day2) == 4
    assert only_day2["timestamp"].dt.date.unique().tolist() == [DAY2.date()]


def test_within_day_time_filter(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 10))  # 09:15 .. 09:24
    result = archive.read_bars("RELIANCE", DAY1 + timedelta(minutes=2), DAY1 + timedelta(minutes=5))
    assert len(result) == 4


def test_list_symbols_sorted(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("INFY", sample_bars("INFY", DAY1, 1))
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    assert list(archive.list_symbols()) == ["INFY", "RELIANCE"]


def test_read_unknown_symbol_returns_empty(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    empty = archive.read_bars("INFY", DAY1, WIDE_END)
    assert empty.empty
    assert list(empty.columns) == list(BAR_COLUMNS)


def test_empty_root_reads_empty_and_lists_nothing(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path / "does_not_exist_yet")
    assert archive.read_bars("RELIANCE", DAY1, WIDE_END).empty
    assert list(archive.list_symbols()) == []


def test_write_empty_frame_is_noop(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 0))
    assert list(archive.list_symbols()) == []
    assert not any(tmp_path.iterdir())


def test_write_rejects_bad_schema(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    with pytest.raises(SchemaError):
        archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1).drop(columns=["open"]))


def test_read_ignores_non_partition_entries(tmp_path: Path) -> None:
    archive = ParquetArchive(tmp_path)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    symbol_dir = tmp_path / "symbol=RELIANCE"
    (symbol_dir / "notes").mkdir()  # not a date= partition
    (symbol_dir / "date=2099-01-01").mkdir()  # date= dir but no bars.parquet file
    result = archive.read_bars("RELIANCE", DAY1, datetime(2099, 12, 31, tzinfo=IST))
    assert len(result) == 3  # the stray dirs are ignored, not read or crashed on


def test_create_parquet_archive_factory(tmp_path: Path) -> None:
    storage = load_config(environ={}).storage.model_copy(
        update={"parquet_path": str(tmp_path / "pq")}
    )
    archive = create_parquet_archive(storage)
    archive.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 2))
    assert len(archive.read_bars("RELIANCE", DAY1, WIDE_END)) == 2
