"""Shared fakes and sample data for the storage-tier unit tests.

The optional backends (ArcticDB, Redis) are exercised through faithful in-memory
fakes that satisfy our narrow Protocols, so the whole P1.3 surface runs with no
``arcticdb``/``redis`` install and no server. The Parquet tier is real (tested against
a ``tmp_path``).

Not a ``test_*`` module, so pytest does not collect it; imported by the store tests.
"""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.data.store.arctic import ArcticSymbolVersion

IST = ZoneInfo("Asia/Kolkata")


def sample_bars(
    symbol: str,
    start: datetime,
    count: int,
    *,
    price: float = 100.0,
    step_minutes: int = 1,
) -> pd.DataFrame:
    """Build ``count`` consecutive minute-spaced bars as a canonical bars frame."""
    bars = [
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(minutes=i * step_minutes),
            open=price + i,
            high=price + i + 1,
            low=price + i - 1,
            close=price + i + 0.5,
            volume=1000 + i,
        )
        for i in range(count)
    ]
    return bars_to_frame(bars)


# --------------------------------------------------------------------- ArcticDB fake


@dataclass(frozen=True)
class FakeVersionedItem:
    """Mirrors the slice of arcticdb's ``VersionedItem`` we read."""

    data: pd.DataFrame
    version: int


@dataclass(frozen=True)
class FakeSymbolVersion:
    """A ``list_versions`` key: identifies one (symbol, version) pair."""

    symbol: str
    version: int


class FakeArcticLibrary:
    """In-memory stand-in for an arcticdb ``Library`` with real version semantics."""

    def __init__(self) -> None:
        self._versions: dict[str, list[pd.DataFrame]] = {}
        self.write_calls: list[tuple[str, bool]] = []

    def write(
        self, symbol: str, data: pd.DataFrame, *, prune_previous_versions: bool = False
    ) -> FakeVersionedItem:
        self.write_calls.append((symbol, prune_previous_versions))
        history = self._versions.setdefault(symbol, [])
        history.append(data.copy())  # store a snapshot; writes never mutate prior versions
        return FakeVersionedItem(data=data, version=len(history) - 1)

    def read(self, symbol: str, *, as_of: int | None = None) -> FakeVersionedItem:
        history = self._versions[symbol]
        version = len(history) - 1 if as_of is None else as_of
        return FakeVersionedItem(data=history[version].copy(), version=version)

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self._versions

    def list_symbols(self) -> list[str]:
        return list(self._versions)

    def list_versions(self, symbol: str) -> Mapping[ArcticSymbolVersion, object]:
        return {
            FakeSymbolVersion(symbol, version): None
            for version in range(len(self._versions[symbol]))
        }


# ----------------------------------------------------------------------- Redis fake


@dataclass
class FakeRedisClient:
    """In-memory stand-in for ``redis.Redis`` (binary-safe key/value + a set)."""

    kv: dict[str, bytes] = field(default_factory=dict)
    sets: dict[str, set[str]] = field(default_factory=dict)
    set_calls: list[tuple[str, int | None]] = field(default_factory=list)

    def get(self, name: str) -> bytes | None:
        return self.kv.get(name)

    def set(self, name: str, value: bytes, ex: int | None = None) -> None:
        self.kv[name] = value
        self.set_calls.append((name, ex))

    def sadd(self, name: str, *values: str) -> None:
        self.sets.setdefault(name, set()).update(values)

    def smembers(self, name: str) -> Set[bytes]:
        return {value.encode("utf-8") for value in self.sets.get(name, set())}
