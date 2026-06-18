"""The pandas bridge for bulk time-series bars (the hybrid data representation).

Bulk bars cross module boundaries as a pandas ``DataFrame`` (the research / feature /
backtest pipeline is pandas-native and vectorised); single live bars stay typed as
:class:`~quant.core.types.Bar`. This module is the *one* place that converts between
the two, with a fixed column schema kept in lock-step with ``Bar``'s fields.
"""

from collections.abc import Sequence
from dataclasses import astuple, fields

import pandas as pd

from quant.core.types import Bar

#: Canonical column order for a bars DataFrame, derived from ``Bar`` so the two
#: representations can never silently drift apart. A test pins the expected names.
BAR_COLUMNS: tuple[str, ...] = tuple(field.name for field in fields(Bar))


def bars_to_frame(bars: Sequence[Bar]) -> pd.DataFrame:
    """Convert typed :class:`Bar` objects to a canonical-schema bars DataFrame."""
    rows = [astuple(bar) for bar in bars]
    return pd.DataFrame(rows, columns=list(BAR_COLUMNS))


def frame_to_bars(frame: pd.DataFrame) -> list[Bar]:
    """Convert a canonical-schema bars DataFrame back to typed :class:`Bar` objects."""
    records = frame[list(BAR_COLUMNS)].to_dict("records")
    return [
        Bar(
            symbol=str(record["symbol"]),
            timestamp=record["timestamp"],
            open=float(record["open"]),
            high=float(record["high"]),
            low=float(record["low"]),
            close=float(record["close"]),
            volume=int(record["volume"]),
        )
        for record in records
    ]
