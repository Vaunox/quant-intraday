"""Storage: the ``Repository`` interface and tiered implementations.

The ``Repository`` Protocol itself lives in :mod:`quant.core.interfaces`; this package
holds the three concrete tiers from Deep Dive #1 §1.2, all behind that one interface
(so they are swappable, and a future ``QuestDBRepository`` drops in unchanged):

* :class:`~quant.data.store.parquet.ParquetArchive` - immutable raw archive (cold),
  ``symbol/date``-partitioned; the point-in-time source of truth.
* :class:`~quant.data.store.arctic.ArcticRepository` - versioned research store (warm);
  every write is a new version. **Optional** backend (``arcticdb`` pins ``pandas<3``).
* :class:`~quant.data.store.redis_store.RedisLiveStore` - bounded recent-bars hot store.
  **Optional** backend (``redis``).

Per Ground Rule 1 / Deep Dive #1 §1.2, the optional database clients are imported only
inside this package (lazily, in their ``create_*`` factories); a confinement test keeps
``arcticdb``/``redis`` out of the rest of the tree.
"""

from quant.data.store.arctic import (
    ArcticLibrary,
    ArcticRepository,
    ArcticSymbolVersion,
    ArcticVersionedItem,
    create_arctic_repository,
    open_arctic_library,
)
from quant.data.store.errors import (
    ImmutableArchiveError,
    OptionalDependencyError,
    SchemaError,
    StorageError,
    VersionNotFoundError,
)
from quant.data.store.parquet import ParquetArchive, create_parquet_archive
from quant.data.store.redis_store import (
    RedisClient,
    RedisLiveStore,
    create_redis_client,
    create_redis_live_store,
)

__all__ = [
    "ArcticLibrary",
    "ArcticRepository",
    "ArcticSymbolVersion",
    "ArcticVersionedItem",
    "ImmutableArchiveError",
    "OptionalDependencyError",
    "ParquetArchive",
    "RedisClient",
    "RedisLiveStore",
    "SchemaError",
    "StorageError",
    "VersionNotFoundError",
    "create_arctic_repository",
    "create_parquet_archive",
    "create_redis_client",
    "create_redis_live_store",
    "open_arctic_library",
]
