"""Deterministic sample data for the leakage suite (bars, depth book, trades, panel).

Seeded so the structural checks and correlation thresholds are reproducible. Not a
``test_*`` module, so pytest does not collect it.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant.core.frames import bars_to_frame
from quant.core.types import Bar, DepthLevel, DepthSnapshot, Tick
from quant.data.features.microstructure import depth_to_frame, trades_to_frame

IST = ZoneInfo("Asia/Kolkata")
_BASE = datetime(2024, 6, 3, 9, 15, tzinfo=IST)


def make_bars(n: int = 120, *, seed: int = 0) -> pd.DataFrame:
    """Return ``n`` minute bars following a seeded random walk (one IST session)."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, n)))
    bars = []
    for i in range(n):
        current = float(close[i])
        open_ = float(close[i - 1]) if i > 0 else current
        high = max(open_, current) * 1.001
        low = min(open_, current) * 0.999
        bars.append(
            Bar("RELIANCE", _BASE + timedelta(minutes=i), open_, high, low, current, 1000 + i)
        )
    return bars_to_frame(bars)


def forward_return(bars: pd.DataFrame) -> pd.Series:
    """Return the next-bar return (a *future* label: realised after the decision at t)."""
    close = bars["close"]
    return (close.shift(-1) / close - 1.0).rename("forward_return")


def make_depth_frame(n: int = 30, *, seed: int = 1) -> pd.DataFrame:
    """Return a depth frame of ``n`` snapshots with a drifting, varying 5-level book."""
    rng = np.random.default_rng(seed)
    snapshots = []
    bid = 100.0
    for i in range(n):
        bid += float(rng.normal(0.0, 0.05))
        ask = bid + 0.1 + abs(float(rng.normal(0.0, 0.02)))
        bids = tuple(
            DepthLevel(bid - 0.05 * level, int(50 + rng.integers(0, 50)), 1) for level in range(5)
        )
        asks = tuple(
            DepthLevel(ask + 0.05 * level, int(50 + rng.integers(0, 50)), 1) for level in range(5)
        )
        snapshots.append(DepthSnapshot("X", _BASE + timedelta(seconds=i), bids, asks))
    return depth_to_frame(snapshots)


def make_trades_frame(n: int = 30, *, seed: int = 2) -> pd.DataFrame:
    """Return a trades frame of ``n`` ticks with a varying price path."""
    rng = np.random.default_rng(seed)
    price = 100.0
    ticks = []
    for i in range(n):
        price += float(rng.normal(0.0, 0.05))
        ticks.append(
            Tick("X", _BASE + timedelta(seconds=i), last_price=price, last_quantity=10, volume=0)
        )
    return trades_to_frame(ticks)


def make_panel(rows: int = 20, *, seed: int = 3) -> pd.DataFrame:
    """Return a wide cross-sectional panel (timestamp index, one column per symbol)."""
    rng = np.random.default_rng(seed)
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    index = [_BASE + timedelta(minutes=i) for i in range(rows)]
    data = {symbol: rng.normal(0.0, 1.0, rows) for symbol in symbols}
    return pd.DataFrame(data, index=index)


#: Sector map for :func:`make_panel`'s symbols (two sectors).
PANEL_SECTORS = {"AAA": "TECH", "BBB": "TECH", "CCC": "BANK", "DDD": "BANK"}
