"""``RedisLiveStore`` — the hot/live store tier.

Deep Dive #1 §1.2 puts Redis at the hot end of the three-tier design: a fast, in-memory
cache of the most *recent* market data for live decisions. This store keeps a bounded
rolling window of the latest bars per symbol (newest ``live_max_bars_per_symbol``),
trimming older ones on each write, with an optional Redis TTL — so memory stays bounded
and stale symbols expire.

Redis is an **optional** backend: its client is confined to this module behind a narrow
:class:`RedisClient` Protocol and imported lazily in :func:`create_redis_client` only,
so the store logic is fully tested against a fake with no ``redis`` install and no
server. Implements :class:`~quant.core.interfaces.Repository`.
"""

from collections.abc import Sequence, Set
from datetime import datetime
from typing import Any, Protocol, cast

import pandas as pd

from quant.core.config import StorageConfig
from quant.core.logging import get_logger
from quant.data.store import serde
from quant.data.store.errors import OptionalDependencyError

_logger = get_logger(__name__)


class RedisClient(Protocol):
    """The subset of ``redis.Redis`` this module uses (binary-safe key/value + a set)."""

    def get(self, name: str) -> bytes | None:
        """Return the value at ``name`` (bytes), or ``None`` if absent."""
        ...

    def set(self, name: str, value: bytes, ex: int | None = None) -> Any:
        """Set ``name`` to ``value``, optionally expiring after ``ex`` seconds."""
        ...

    def sadd(self, name: str, *values: str) -> Any:
        """Add ``values`` to the set at ``name``."""
        ...

    def smembers(self, name: str) -> Set[bytes]:
        """Return the members (bytes) of the set at ``name``.

        Typed as the abstract ``Set`` (not the builtin ``set``, which the ``set``
        method above shadows in this class body); the real client returns a ``set``.
        """
        ...


class RedisLiveStore:
    """A bounded, recent-bars hot store backed by Redis (a ``Repository``)."""

    def __init__(
        self,
        client: RedisClient,
        *,
        key_prefix: str,
        max_bars: int,
        ttl_seconds: int = 0,
    ) -> None:
        """Build the live store.

        Args:
            client: The Redis client (behind :class:`RedisClient`).
            key_prefix: Namespace for this system's keys within a shared Redis.
            max_bars: Rolling-window size — only the newest this-many bars per symbol
                are retained (must be > 0).
            ttl_seconds: Optional per-symbol key TTL; ``0`` disables time-based expiry.

        Raises:
            ValueError: If ``max_bars`` is not positive.
        """
        if max_bars <= 0:
            raise ValueError(f"max_bars must be positive, got {max_bars!r}")
        self._client = client
        self._prefix = key_prefix
        self._max_bars = max_bars
        self._ttl = ttl_seconds

    # ------------------------------------------------------------------ writing
    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        """Merge ``bars`` into ``symbol``'s rolling window, newest ``max_bars`` kept.

        Idempotent: re-writing already-stored bars leaves the window unchanged (rows
        are de-duplicated by timestamp, with the newly written values winning on a tie).

        Args:
            symbol: The instrument symbol.
            bars: A canonical-schema bars DataFrame.

        Raises:
            SchemaError: If ``bars`` is not in the canonical schema.
        """
        frame = serde.ensure_bars_schema(bars)
        if frame.empty:
            _logger.debug("redis live store: nothing to write", extra={"symbol": symbol})
            return
        window = self._merge_window(self._read_frame(symbol), frame)
        ttl = self._ttl if self._ttl > 0 else None
        self._client.set(self._bars_key(symbol), serde.to_parquet_bytes(window), ex=ttl)
        self._client.sadd(self._symbols_key(), symbol)
        _logger.debug(
            "redis live store: updated window",
            extra={"symbol": symbol, "window_rows": len(window), "ttl": ttl},
        )

    def _merge_window(self, existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
        """Concatenate, de-duplicate by timestamp (incoming wins), sort, trim to ``max_bars``."""
        # Concat existing-then-incoming so keep="last" lets incoming win on equal timestamps.
        combined = pd.concat([existing, incoming], ignore_index=True)
        deduped = combined.drop_duplicates(subset=serde.TIME_COLUMN, keep="last")
        return serde.sort_bars(deduped).tail(self._max_bars).reset_index(drop=True)

    # ------------------------------------------------------------------ reading
    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Read the retained bars for ``symbol`` within ``[start, end]`` (inclusive)."""
        return serde.restrict_to_range(self._read_frame(symbol), start, end)

    def list_symbols(self) -> Sequence[str]:
        """Return the symbols currently held in the hot store, sorted."""
        members = self._client.smembers(self._symbols_key())
        return sorted(member.decode("utf-8") for member in members)

    # ------------------------------------------------------------------ helpers
    def _read_frame(self, symbol: str) -> pd.DataFrame:
        """Load a symbol's stored window, or an empty frame if absent."""
        blob = self._client.get(self._bars_key(symbol))
        if blob is None:
            return serde.empty_bars_frame()
        return serde.from_parquet_bytes(blob)

    def _bars_key(self, symbol: str) -> str:
        """Redis key holding ``symbol``'s rolling bars window."""
        return f"{self._prefix}:bars:{symbol}"

    def _symbols_key(self) -> str:
        """Redis key holding the set of symbols present in the store."""
        return f"{self._prefix}:symbols"


def create_redis_client(url: str) -> RedisClient:
    """Construct a real ``redis.Redis`` client — the single ``redis`` import site.

    Args:
        url: Redis connection URL (e.g. ``redis://localhost:6379/0``).

    Returns:
        A client typed as :class:`RedisClient`.

    Raises:
        OptionalDependencyError: If ``redis`` is not installed.
    """
    try:
        from redis import Redis
    except ImportError as exc:
        raise OptionalDependencyError(
            "redis is not installed. Install the hot-store backend with "
            "`uv sync --extra redis` (or `pip install redis`)."
        ) from exc
    return cast(RedisClient, Redis.from_url(url))  # pragma: no cover - needs redis installed


def create_redis_live_store(storage: StorageConfig) -> RedisLiveStore:
    """Build a :class:`RedisLiveStore` from the storage configuration."""
    return RedisLiveStore(
        create_redis_client(storage.redis_url),
        key_prefix=storage.redis_key_prefix,
        max_bars=storage.live_max_bars_per_symbol,
        ttl_seconds=storage.live_ttl_seconds,
    )
