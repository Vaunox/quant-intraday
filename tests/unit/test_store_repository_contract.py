"""Shared ``Repository`` contract, run against all three tiers (P1.3).

The acceptance criterion "swappable behind the interface" means every tier must honour
the same :class:`~quant.core.interfaces.Repository` behaviour. These tests are
parametrized over Parquet (real), Arctic (fake library), and Redis (fake client), so a
divergence in any tier fails here.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant.core.frames import BAR_COLUMNS
from quant.core.interfaces import Repository
from quant.data.store import ArcticRepository, ParquetArchive, RedisLiveStore
from tests.unit.store_fakes import IST, FakeArcticLibrary, FakeRedisClient, sample_bars

DAY1 = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
HOUR = timedelta(hours=1)

_BUILDERS: dict[str, Callable[[Path], Repository]] = {
    "parquet": lambda tmp: ParquetArchive(tmp / "pq"),
    "arctic": lambda _tmp: ArcticRepository(FakeArcticLibrary()),
    "redis": lambda _tmp: RedisLiveStore(FakeRedisClient(), key_prefix="quant", max_bars=1000),
}


@pytest.fixture(params=list(_BUILDERS), ids=list(_BUILDERS))
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Repository:
    """A fresh repository of each tier."""
    return _BUILDERS[request.param](tmp_path)


def test_is_a_repository(repo: Repository) -> None:
    assert isinstance(repo, Repository)


def test_write_then_read_roundtrip(repo: Repository) -> None:
    bars = sample_bars("RELIANCE", DAY1, 5)
    repo.write_bars("RELIANCE", bars)
    pd.testing.assert_frame_equal(repo.read_bars("RELIANCE", DAY1, DAY1 + HOUR), bars)


def test_double_write_is_idempotent(repo: Repository) -> None:
    bars = sample_bars("RELIANCE", DAY1, 3)
    repo.write_bars("RELIANCE", bars)
    repo.write_bars("RELIANCE", bars)
    pd.testing.assert_frame_equal(repo.read_bars("RELIANCE", DAY1, DAY1 + HOUR), bars)


def test_list_symbols_reflects_writes(repo: Repository) -> None:
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    repo.write_bars("INFY", sample_bars("INFY", DAY1, 1))
    assert list(repo.list_symbols()) == ["INFY", "RELIANCE"]


def test_read_unknown_symbol_is_empty_with_schema(repo: Repository) -> None:
    result = repo.read_bars("RELIANCE", DAY1, DAY1 + HOUR)
    assert result.empty
    assert list(result.columns) == list(BAR_COLUMNS)


def test_range_filter_is_inclusive_subset(repo: Repository) -> None:
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 6))  # 09:15 .. 09:20
    result = repo.read_bars("RELIANCE", DAY1 + timedelta(minutes=1), DAY1 + timedelta(minutes=3))
    assert len(result) == 3


def test_read_range_before_data_is_empty(repo: Repository) -> None:
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    result = repo.read_bars("RELIANCE", DAY1 - timedelta(days=2), DAY1 - timedelta(days=1))
    assert result.empty
