"""Shared serialization, schema-validation, and range helpers for the storage tiers.

One place owns how a bars :class:`~pandas.DataFrame` is validated, ordered, range-
filtered, and (de)serialized, so every tier behaves identically and the canonical
schema (:data:`quant.core.frames.BAR_COLUMNS`) can never drift between them.

Bars are serialized with Parquet (via pyarrow) for both the file archive and the
Redis value blobs: it is compact, columnar, and — verified by the round-trip tests —
preserves the exact dtypes (tz-aware ``timestamp``, ``int64`` volume, ``float64``
OHLC), so a write/read cycle is bit-faithful.
"""

import io
from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from quant.core.frames import BAR_COLUMNS, bars_to_frame
from quant.data.store.errors import SchemaError

#: The canonical bars columns as a set, for fast membership/equality checks.
_BAR_COLUMN_SET = frozenset(BAR_COLUMNS)

#: Column carrying each bar's close time (tz-aware IST); the time axis we sort/filter on.
TIME_COLUMN = "timestamp"


def empty_bars_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical bars columns.

    Used as the well-typed "no rows" result for reads of an unknown symbol or an
    empty range, so callers always get the same schema back.
    """
    return bars_to_frame([])


def ensure_bars_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate ``frame`` against the canonical bars schema and return it column-ordered.

    Args:
        frame: A candidate bars DataFrame.

    Returns:
        The same data with columns in canonical :data:`BAR_COLUMNS` order.

    Raises:
        SchemaError: If the columns are not exactly the canonical set (a malformed
            write must fail at the boundary, not corrupt a backend).
    """
    columns = set(frame.columns)
    if columns != _BAR_COLUMN_SET:
        missing = sorted(_BAR_COLUMN_SET - columns)
        extra = sorted(columns - _BAR_COLUMN_SET)
        raise SchemaError(
            "bars frame does not match the canonical schema "
            f"{list(BAR_COLUMNS)}; missing={missing}, unexpected={extra}"
        )
    # Reorder defensively so downstream serialization/comparison is order-independent.
    return frame.loc[:, list(BAR_COLUMNS)]


def sort_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` sorted by timestamp ascending with a fresh range index."""
    return frame.sort_values(TIME_COLUMN, kind="stable").reset_index(drop=True)


def restrict_to_range(frame: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    """Return the rows of ``frame`` with ``start <= timestamp <= end`` (inclusive), sorted.

    The range bounds must be timezone-aware (the system's timestamps are IST); a naive
    bound raises loudly from pandas rather than silently comparing wrong.
    """
    if frame.empty:
        return empty_bars_frame()
    times = frame[TIME_COLUMN]
    mask = (times >= start) & (times <= end)
    return sort_bars(frame.loc[mask])


def to_parquet_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize a bars DataFrame to Parquet bytes (no index)."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer, engine="pyarrow", index=False)
    return buffer.getvalue()


def from_parquet_bytes(data: bytes) -> pd.DataFrame:
    """Deserialize Parquet bytes back to a bars DataFrame."""
    # engine left at the default "auto" (which resolves to the installed pyarrow);
    # naming it explicitly trips a pandas-stubs overload that then demands an unrelated
    # ``to_pandas_kwargs`` argument.
    return pd.read_parquet(io.BytesIO(data))


def frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    """Whether two bars frames hold identical content (order-insensitive).

    Both sides are sorted to a canonical order first, so two writes of the same bars
    in a different row order count as equal — which is what idempotency and the
    immutable-archive identical-rewrite check need.
    """
    return sort_bars(left).equals(sort_bars(right))


def concat_bars(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate bars frames into one sorted frame (empty-safe)."""
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return empty_bars_frame()
    return sort_bars(pd.concat(non_empty, ignore_index=True))
