"""Tests for ArcticRepository — the versioned research tier (P1.3).

ArcticDB is optional and pins pandas<3, so it is not installed in CI; the repository
logic is verified against :class:`FakeArcticLibrary`, which reproduces arcticdb's
version semantics. The lazy factory's missing-dependency path is also exercised.
"""

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant.core.config import load_config
from quant.core.frames import BAR_COLUMNS
from quant.core.interfaces import Repository
from quant.data.store.arctic import (
    ArcticRepository,
    create_arctic_repository,
    open_arctic_library,
)
from quant.data.store.errors import OptionalDependencyError, SchemaError, VersionNotFoundError
from tests.unit.store_fakes import IST, FakeArcticLibrary, sample_bars

DAY1 = datetime(2026, 6, 18, 9, 15, tzinfo=IST)
HOUR = timedelta(hours=1)
_ARCTICDB_INSTALLED = importlib.util.find_spec("arcticdb") is not None


def _repo() -> tuple[ArcticRepository, FakeArcticLibrary]:
    library = FakeArcticLibrary()
    return ArcticRepository(library), library


def test_is_a_repository() -> None:
    repo, _ = _repo()
    assert isinstance(repo, Repository)


def test_write_read_roundtrip() -> None:
    repo, _ = _repo()
    bars = sample_bars("RELIANCE", DAY1, 4)
    repo.write_bars("RELIANCE", bars)
    pd.testing.assert_frame_equal(repo.read_bars("RELIANCE", DAY1, DAY1 + HOUR), bars)


def test_first_write_is_version_zero() -> None:
    repo, _ = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 2))
    assert repo.list_versions("RELIANCE") == [0]
    assert repo.latest_version("RELIANCE") == 0


def test_identical_rewrite_creates_no_new_version() -> None:
    repo, library = _repo()
    bars = sample_bars("RELIANCE", DAY1, 3)
    repo.write_bars("RELIANCE", bars)
    repo.write_bars("RELIANCE", bars)  # identical content
    assert repo.list_versions("RELIANCE") == [0]
    assert library.write_calls == [("RELIANCE", False)]  # only the first write hit the library


def test_changed_data_creates_new_version_and_preserves_old() -> None:
    repo, _ = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 3))
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 5))  # a correction/extension
    assert repo.list_versions("RELIANCE") == [0, 1]
    assert repo.latest_version("RELIANCE") == 1
    assert len(repo.read_bars("RELIANCE", DAY1, DAY1 + HOUR)) == 5  # latest
    assert len(repo.read_bars_version("RELIANCE", DAY1, DAY1 + HOUR, 0)) == 3  # time travel


def test_write_passes_prune_previous_versions_false() -> None:
    # Versions must accumulate (corrections become history), so writes never prune.
    repo, library = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    assert library.write_calls == [("RELIANCE", False)]


def test_read_bars_version_unknown_raises() -> None:
    repo, _ = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 2))
    with pytest.raises(VersionNotFoundError, match="version 7"):
        repo.read_bars_version("RELIANCE", DAY1, DAY1 + HOUR, 7)


def test_range_filter_on_latest_version() -> None:
    repo, _ = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 10))
    result = repo.read_bars("RELIANCE", DAY1 + timedelta(minutes=2), DAY1 + timedelta(minutes=4))
    assert len(result) == 3


def test_list_symbols_sorted() -> None:
    repo, _ = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1))
    repo.write_bars("INFY", sample_bars("INFY", DAY1, 1))
    assert list(repo.list_symbols()) == ["INFY", "RELIANCE"]


def test_unknown_symbol_reads_empty_and_has_no_versions() -> None:
    repo, _ = _repo()
    empty = repo.read_bars("INFY", DAY1, DAY1 + HOUR)
    assert empty.empty
    assert list(empty.columns) == list(BAR_COLUMNS)
    assert repo.list_versions("INFY") == []
    assert repo.latest_version("INFY") is None


def test_empty_write_is_noop() -> None:
    repo, library = _repo()
    repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 0))
    assert library.write_calls == []
    assert repo.list_versions("RELIANCE") == []


def test_write_rejects_bad_schema() -> None:
    repo, _ = _repo()
    with pytest.raises(SchemaError):
        repo.write_bars("RELIANCE", sample_bars("RELIANCE", DAY1, 1).drop(columns=["close"]))


@pytest.mark.skipif(_ARCTICDB_INSTALLED, reason="arcticdb installed; missing-dep path not hit")
def test_open_arctic_library_without_arcticdb_raises() -> None:
    with pytest.raises(OptionalDependencyError, match="ArcticDB is not installed"):
        open_arctic_library("lmdb://unused", "bars")


@pytest.mark.skipif(_ARCTICDB_INSTALLED, reason="arcticdb installed; missing-dep path not hit")
def test_create_arctic_repository_without_arcticdb_raises(tmp_path: Path) -> None:
    storage = load_config(environ={}).storage.model_copy(
        update={"arctic_uri": f"lmdb://{tmp_path}"}
    )
    with pytest.raises(OptionalDependencyError):
        create_arctic_repository(storage)
