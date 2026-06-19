"""Exceptions raised by the storage tier.

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can distinguish a schema violation from an attempt to mutate
the immutable archive from a missing optional backend, instead of catching a bare
``RuntimeError``.
"""


class StorageError(RuntimeError):
    """Base class for all storage-tier errors."""


class SchemaError(StorageError):
    """A DataFrame did not match the canonical bars schema.

    Raised at the write boundary so malformed data never reaches a backend (the raw
    archive in particular is immutable, so a bad write cannot simply be corrected).
    """


class ImmutableArchiveError(StorageError):
    """An attempt was made to overwrite existing raw-archive data with different data.

    The Parquet raw archive is append-only and immutable (Deep Dive #1 §1.2: "you
    never overwrite history; corrections become new versions"). Re-writing *identical*
    data is a no-op; re-writing *different* data for an already-archived ``symbol/date``
    raises this — corrections belong in the versioned research store, not here.
    """


class VersionNotFoundError(StorageError):
    """A specific version was requested for a symbol that has no such version."""


class OptionalDependencyError(StorageError):
    """An optional storage backend was used but its package is not installed.

    The ArcticDB and Redis tiers are optional (see ``pyproject.toml``); their clients
    are imported lazily, and this is raised with install guidance if the import fails.
    """
