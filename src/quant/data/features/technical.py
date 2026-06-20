"""Technical-indicator features via TA-Lib (Deep Dive #1 §2.2.D).

*"Momentum / mean-reversion technicals via **TA-Lib**, never hand-rolled — indicator bugs
are insidious. Treat these as weak features to be combined, not standalone strategies."*

Thin, typed wrappers around TA-Lib that return pandas Series aligned to the bars index.
TA-Lib operates on contiguous ``float64`` numpy arrays and is the single dependency
isolated to this module. Indicators are causal (trailing windows), so they are
point-in-time correct and warm up with leading ``NaN``s.
"""

import numpy as np
import pandas as pd
import talib


def _close(bars: pd.DataFrame) -> np.ndarray:
    """Return the close column as a contiguous float64 array for TA-Lib."""
    return bars["close"].to_numpy(dtype="float64")


def rsi(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the Relative Strength Index over ``period`` bars (0-100).

    Raises:
        ValueError: If ``period <= 1``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    values = talib.RSI(_close(bars), timeperiod=period)
    return pd.Series(values, index=bars.index, name=f"rsi_{period}")


def macd_histogram(bars: pd.DataFrame, *, fast: int, slow: int, signal: int) -> pd.Series:
    """Return the MACD histogram (MACD line minus signal line).

    Raises:
        ValueError: If periods are not positive or ``fast >= slow``.
    """
    if min(fast, slow, signal) <= 0:
        raise ValueError(f"MACD periods must be positive, got {fast}, {slow}, {signal}")
    if fast >= slow:
        raise ValueError(f"MACD fast ({fast}) must be < slow ({slow})")
    _, _, histogram = talib.MACD(
        _close(bars), fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    return pd.Series(histogram, index=bars.index, name="macd_hist")


def bollinger_percent_b(bars: pd.DataFrame, *, period: int, num_std: float) -> pd.Series:
    """Return Bollinger %B = ``(close - lower) / (upper - lower)``.

    %B places the close within its Bollinger band (0 = lower band, 1 = upper). Where the
    band has zero width (a flat window) the value is ``NaN`` rather than a divide-by-zero.

    Raises:
        ValueError: If ``period <= 1`` or ``num_std <= 0``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive, got {num_std!r}")
    close = _close(bars)
    upper, _, lower = talib.BBANDS(close, timeperiod=period, nbdevup=num_std, nbdevdn=num_std)
    width = upper - lower
    percent_b = np.divide(close - lower, width, out=np.full_like(close, np.nan), where=width != 0)
    return pd.Series(percent_b, index=bars.index, name="bbands_percent_b")
