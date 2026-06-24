"""Tests for the post-backfill data-quality check (P2A.3, ``check_cli``).

Drives the read-only verifier against a fake Repository (canned bars per symbol) and the real
P1.5/P1.9 stack: a symbol with no data is flagged (and makes ``main`` exit non-zero), while a
populated universe passes. No broker, no network.
"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from quant.core.config import Config, load_config
from quant.data.ingest.backfill import day_end, day_start
from quant.data.ingest.check_cli import BackfillCheck, check_backfill, main
from tests.unit.hygiene_fakes import at, frame, good

REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"
D1, D2, D3 = date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)  # Mon-Wed trading days
START, END = day_start(D1), day_end(D3)


class _FakeRepository:
    """A minimal in-memory ``Repository`` returning canned bars per symbol."""

    def __init__(self, bars: dict[str, pd.DataFrame]) -> None:
        self._bars = bars

    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self._bars.get(symbol, frame([]))

    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:  # unused by the verifier
        self._bars[symbol] = bars

    def list_symbols(self) -> list[str]:
        return list(self._bars)


def _bars(symbol: str) -> pd.DataFrame:
    return frame([good(symbol, at(D1, 9, 15 + i), 100.0 + i) for i in range(3)])


def _config() -> Config:
    return load_config(env="dev", environ={"QUANT_CONFIG_DIR": str(REPO_CONFIG)})


def test_check_backfill_flags_empty_symbols() -> None:
    repo = _FakeRepository({"GOOD": _bars("GOOD"), "EMPTY": frame([])})
    check = check_backfill(_config(), repo, ["GOOD", "EMPTY"], start=START, end=END)
    assert isinstance(check, BackfillCheck)
    assert check.empty_symbols == ("EMPTY",)
    assert not check.ok


def test_check_backfill_ok_when_all_symbols_have_data() -> None:
    repo = _FakeRepository({"GOOD": _bars("GOOD")})
    check = check_backfill(_config(), repo, ["GOOD"], start=START, end=END)
    assert check.ok
    assert check.empty_symbols == ()
    assert check.report.symbols[0].coverage.observed_bars == 3  # the 3 bars we wrote


def test_main_returns_one_when_a_symbol_is_empty() -> None:
    repo = _FakeRepository({"GOOD": _bars("GOOD"), "EMPTY": frame([])})
    code = main(
        ["--start", "2024-06-03", "--end", "2024-06-05", "--symbols", "GOOD", "EMPTY"],
        environ={"QUANT_CONFIG_DIR": str(REPO_CONFIG)},
        repository_factory=lambda config, tier: repo,
    )
    assert code == 1


def test_main_returns_zero_when_all_symbols_have_data() -> None:
    repo = _FakeRepository({"GOOD": _bars("GOOD")})
    code = main(
        ["--start", "2024-06-03", "--end", "2024-06-05", "--symbols", "GOOD"],
        environ={"QUANT_CONFIG_DIR": str(REPO_CONFIG)},
        repository_factory=lambda config, tier: repo,
    )
    assert code == 0
