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


def _hlc(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (high, low, close) as contiguous float64 arrays for TA-Lib."""
    return (
        bars["high"].to_numpy(dtype="float64"),
        bars["low"].to_numpy(dtype="float64"),
        bars["close"].to_numpy(dtype="float64"),
    )


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


def bollinger_bands(bars: pd.DataFrame, *, period: int, num_std: float) -> pd.DataFrame:
    """Return the raw upper/lower Bollinger bands (price levels) as a two-column frame.

    Unlike :func:`bollinger_percent_b` (a bounded oscillator), these are *price-level*
    series — non-stationary, intended to be fractionally differenced before modelling.

    Raises:
        ValueError: If ``period <= 1`` or ``num_std <= 0``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive, got {num_std!r}")
    upper, _, lower = talib.BBANDS(
        _close(bars), timeperiod=period, nbdevup=num_std, nbdevdn=num_std
    )
    return pd.DataFrame({"boll_ub": upper, "boll_lb": lower}, index=bars.index)


def macd_line(bars: pd.DataFrame, *, fast: int, slow: int, signal: int) -> pd.Series:
    """Return the raw MACD line (fast EMA minus slow EMA of the close).

    The line itself (a difference of EMAs), distinct from :func:`macd_histogram` (line minus
    signal). Near-stationary but kept as a separate feature for parity with the prior config.

    Raises:
        ValueError: If periods are not positive or ``fast >= slow``.
    """
    if min(fast, slow, signal) <= 0:
        raise ValueError(f"MACD periods must be positive, got {fast}, {slow}, {signal}")
    if fast >= slow:
        raise ValueError(f"MACD fast ({fast}) must be < slow ({slow})")
    line, _, _ = talib.MACD(_close(bars), fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return pd.Series(line, index=bars.index, name="macd_line")


def cci(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the Commodity Channel Index over ``period`` bars (unbounded oscillator).

    Raises:
        ValueError: If ``period <= 1``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    high, low, close = _hlc(bars)
    return pd.Series(
        talib.CCI(high, low, close, timeperiod=period), index=bars.index, name=f"cci_{period}"
    )


def directional_index(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the Directional Movement Index (DX) over ``period`` bars (0-100).

    Raises:
        ValueError: If ``period <= 1``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    high, low, close = _hlc(bars)
    return pd.Series(
        talib.DX(high, low, close, timeperiod=period), index=bars.index, name=f"dx_{period}"
    )


def williams_r(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return Williams %R over ``period`` bars (-100 to 0; a bounded oscillator).

    Raises:
        ValueError: If ``period <= 1``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    high, low, close = _hlc(bars)
    return pd.Series(
        talib.WILLR(high, low, close, timeperiod=period), index=bars.index, name=f"wr_{period}"
    )


def money_flow_index(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the Money Flow Index over ``period`` bars (0-100; volume-weighted RSI).

    Raises:
        ValueError: If ``period <= 1``.
    """
    if period <= 1:
        raise ValueError(f"period must be > 1, got {period!r}")
    high, low, close = _hlc(bars)
    volume = bars["volume"].to_numpy(dtype="float64")
    return pd.Series(
        talib.MFI(high, low, close, volume, timeperiod=period),
        index=bars.index,
        name=f"mfi_{period}",
    )


def sma(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the simple moving average of the close over ``period`` bars (a price level).

    A *price-level* feature (non-stationary) — intended to be fractionally differenced.

    Raises:
        ValueError: If ``period < 1``.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period!r}")
    return pd.Series(
        talib.SMA(_close(bars), timeperiod=period), index=bars.index, name=f"sma_{period}"
    )


def volume_weighted_ma(bars: pd.DataFrame, period: int) -> pd.Series:
    """Return the rolling volume-weighted moving average of the close over ``period`` bars.

    ``Σ(close·volume) / Σ(volume)`` over a trailing window — causal (uses only bars at or
    before ``t``). A *price-level* feature (non-stationary), intended to be frac-differenced.
    TA-Lib has no native VWMA, so it is composed from rolling sums (still point-in-time).

    Raises:
        ValueError: If ``period < 1``.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period!r}")
    close = bars["close"].astype("float64")
    volume = bars["volume"].astype("float64")
    numerator = (close * volume).rolling(period, min_periods=period).sum()
    denominator = volume.rolling(period, min_periods=period).sum()
    vwma = numerator / denominator.where(denominator != 0)
    return pd.Series(vwma.to_numpy(), index=bars.index, name=f"vwma_{period}")
