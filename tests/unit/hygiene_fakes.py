"""Shared bar builders for the data-hygiene unit tests.

Small helpers to construct canonical bars frames with explicit OHLCV (hygiene tests
need precise prices — splits, bad ticks, gaps). Not a ``test_*`` module, so pytest does
not collect it; imported by the hygiene tests.
"""

from collections.abc import Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.types import Bar

IST = ZoneInfo("Asia/Kolkata")


def at(day: date, hour: int = 9, minute: int = 15) -> datetime:
    """Return an IST instant on ``day`` at ``hour:minute``."""
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


def bar(symbol: str, ts: datetime, *, o: float, h: float, lo: float, c: float, v: int) -> Bar:
    """Build a single :class:`Bar` with explicit OHLCV."""
    return Bar(symbol=symbol, timestamp=ts, open=o, high=h, low=lo, close=c, volume=v)


def good(symbol: str, ts: datetime, close: float, vol: int = 10) -> Bar:
    """Build a structurally-valid bar centred on ``close`` (high/low bracket it)."""
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=vol,
    )


def frame(bars: Sequence[Bar]) -> pd.DataFrame:
    """Convert bars to a canonical-schema DataFrame."""
    return bars_to_frame(bars)
