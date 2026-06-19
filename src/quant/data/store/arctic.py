"""``ArcticRepository`` — the versioned research store tier (warm storage).

Deep Dive #1 §1.2 makes ArcticDB the recommended warm/research store precisely for its
**versioning**: every write is a new immutable version, giving point-in-time dataset
snapshots that "directly fight lookahead/leakage". A correction does not mutate
history — it creates a new version, and an old version stays readable forever.

ArcticDB is an **optional** backend (it pins ``pandas<3``; see ``pyproject.toml``), so
its SDK is confined to this module behind a narrow :class:`ArcticLibrary` Protocol and
imported lazily in :func:`open_arctic_library` only. Everything else — and every test —
programs against the Protocol, so the repository logic runs against a fake library with
no ``arcticdb`` install.

Implements :class:`~quant.core.interfaces.Repository` and adds version-aware reads
(:meth:`ArcticRepository.read_bars_version`, :meth:`ArcticRepository.list_versions`).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, cast, runtime_checkable

import pandas as pd

from quant.core.config import StorageConfig
from quant.core.logging import get_logger
from quant.data.store import serde
from quant.data.store.errors import OptionalDependencyError, VersionNotFoundError

_logger = get_logger(__name__)


@runtime_checkable
class ArcticVersionedItem(Protocol):
    """The slice of ArcticDB's ``VersionedItem`` we read: the data and its version."""

    @property
    def data(self) -> pd.DataFrame:
        """The stored DataFrame for this version."""
        ...

    @property
    def version(self) -> int:
        """The integer version number of this item."""
        ...


@runtime_checkable
class ArcticSymbolVersion(Protocol):
    """A key in ``list_versions``: identifies one (symbol, version) pair."""

    @property
    def version(self) -> int:
        """The integer version number."""
        ...


class ArcticLibrary(Protocol):
    """The subset of ``arcticdb.version_store.library.Library`` this module uses.

    Method names/shapes mirror the real SDK so an ``arcticdb`` ``Library`` satisfies
    this Protocol structurally (we cast to it in :func:`open_arctic_library`).
    """

    def write(
        self, symbol: str, data: pd.DataFrame, *, prune_previous_versions: bool = False
    ) -> ArcticVersionedItem:
        """Write ``data`` as a new version of ``symbol`` and return the versioned item."""
        ...

    def read(self, symbol: str, *, as_of: int | None = None) -> ArcticVersionedItem:
        """Read a version of ``symbol`` (latest, or ``as_of`` a version number)."""
        ...

    def has_symbol(self, symbol: str) -> bool:
        """Whether ``symbol`` exists in the library."""
        ...

    def list_symbols(self) -> list[str]:
        """List the symbols held in the library."""
        ...

    def list_versions(self, symbol: str) -> Mapping[ArcticSymbolVersion, Any]:
        """Map each version key (with a ``.version``) of ``symbol`` to its info."""
        ...


class ArcticRepository:
    """Versioned bars store over an ArcticDB library (a ``Repository``)."""

    def __init__(self, library: ArcticLibrary) -> None:
        """Build the repository over an (already opened) :class:`ArcticLibrary`."""
        self._library = library

    # ------------------------------------------------------------------ writing
    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        """Write ``bars`` for ``symbol`` as a new version (idempotent on no change).

        To keep version history meaningful, a write whose content is identical to the
        symbol's current latest version is a no-op (no empty version is created);
        genuinely changed data becomes a new version (a correction, never an overwrite).

        Args:
            symbol: The instrument symbol.
            bars: A canonical-schema bars DataFrame.

        Raises:
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.sort_bars(serde.ensure_bars_schema(bars))
        if frame.empty:
            _logger.debug("arctic: nothing to write", extra={"symbol": symbol})
            return
        if self._library.has_symbol(symbol):
            current = self._library.read(symbol).data
            if serde.frames_equal(current, frame):
                _logger.debug(
                    "arctic: latest version identical, skipping", extra={"symbol": symbol}
                )
                return
        item = self._library.write(symbol, frame, prune_previous_versions=False)
        _logger.info(
            "arctic: wrote version",
            extra={"symbol": symbol, "version": item.version, "rows": len(frame)},
        )

    # ------------------------------------------------------------------ reading
    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Read the latest version of ``symbol`` within ``[start, end]`` (inclusive)."""
        if not self._library.has_symbol(symbol):
            return serde.empty_bars_frame()
        data = self._library.read(symbol).data
        return serde.restrict_to_range(data, start, end)

    def read_bars_version(
        self, symbol: str, start: datetime, end: datetime, version: int
    ) -> pd.DataFrame:
        """Read a specific ``version`` of ``symbol`` within ``[start, end]`` (time travel).

        Raises:
            VersionNotFoundError: If ``symbol`` has no such version.
        """
        if version not in self.list_versions(symbol):
            raise VersionNotFoundError(f"{symbol} has no version {version}")
        data = self._library.read(symbol, as_of=version).data
        return serde.restrict_to_range(data, start, end)

    def list_symbols(self) -> Sequence[str]:
        """Return the symbols held in the store, sorted."""
        return sorted(self._library.list_symbols())

    def list_versions(self, symbol: str) -> list[int]:
        """Return the version numbers held for ``symbol``, ascending (empty if unknown)."""
        if not self._library.has_symbol(symbol):
            return []
        return sorted(key.version for key in self._library.list_versions(symbol))

    def latest_version(self, symbol: str) -> int | None:
        """Return the newest version number for ``symbol``, or ``None`` if unknown."""
        versions = self.list_versions(symbol)
        return versions[-1] if versions else None


def open_arctic_library(uri: str, library: str) -> ArcticLibrary:
    """Open (creating if needed) an ArcticDB library — the single ``arcticdb`` import site.

    Args:
        uri: ArcticDB storage URI (e.g. ``lmdb://data/arctic``, ``s3://...``).
        library: Library name holding the bars dataset.

    Returns:
        The opened library typed as :class:`ArcticLibrary`.

    Raises:
        OptionalDependencyError: If ``arcticdb`` is not installed.
    """
    try:
        from arcticdb import Arctic
    except ImportError as exc:
        raise OptionalDependencyError(
            "ArcticDB is not installed. Install it in a pandas<3 environment, e.g. "
            '`pip install "arcticdb>=5,<7"` (the warm research tier is optional).'
        ) from exc
    arctic = Arctic(uri)  # pragma: no cover - reached only with arcticdb installed
    return cast(  # pragma: no cover - reached only with arcticdb installed
        ArcticLibrary, arctic.get_library(library, create_if_missing=True)
    )


def create_arctic_repository(storage: StorageConfig) -> ArcticRepository:
    """Build an :class:`ArcticRepository` from the storage configuration."""
    return ArcticRepository(open_arctic_library(storage.arctic_uri, storage.arctic_library))
