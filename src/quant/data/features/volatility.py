"""Volatility features (Deep Dive #1 §2.2.C).

Realized volatility (rolling std of returns), ATR, and the Parkinson high-low range
estimator. Volatility is both a feature *and* the basis for position sizing (Deep Dive
#3). Each function is a **pure, causal** transform: trailing rolling windows only, so the
value at row *t* uses only bars at or before *t* (point-in-time correct, §2.1).

Inputs are expected to be hygiene-clean, corporate-action *adjusted* bars.
"""

import numpy as np
import pandas as pd

from quant.data.features.returns import log_return

#: Parkinson estimator constant 1 / (4 ln 2): variance = mean(ln(H/L)^2) * this.
_PARKINSON_FACTOR = 1.0 / (4.0 * np.log(2.0))


def realized_volatility(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the rolling standard deviation of 1-bar log returns over ``window`` bars.

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        window: Rolling window length in bars (must be > 1 for a defined std).

    Raises:
        ValueError: If ``window`` is not greater than 1.
    """
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window!r}")
    returns = log_return(bars, 1)
    return returns.rolling(window).std().rename(f"rvol_{window}")


def atr(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the Average True Range over ``window`` bars (Wilder's true range, SMA).

    True range is ``max(high-low, |high-prev_close|, |low-prev_close|)``; ATR is its
    rolling mean. Causal (uses the *previous* close), so point-in-time correct.

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        window: Rolling window length in bars (must be > 1).

    Raises:
        ValueError: If ``window`` is not greater than 1.
    """
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window!r}")
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(window).mean().rename(f"atr_{window}")


def parkinson_volatility(bars: pd.DataFrame, window: int) -> pd.Series:
    """Return the Parkinson high-low range volatility over ``window`` bars.

    ``sqrt( mean(ln(high/low)^2) / (4 ln 2) )`` over the trailing window — a range-based
    estimator that is more efficient than close-to-close vol when OHLC is available.

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        window: Rolling window length in bars (must be > 1).

    Raises:
        ValueError: If ``window`` is not greater than 1.
    """
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window!r}")
    log_hl = np.log(bars["high"] / bars["low"])
    squared = pd.Series(log_hl * log_hl, index=bars.index)
    variance = _PARKINSON_FACTOR * squared.rolling(window).mean()
    return pd.Series(np.sqrt(variance), index=bars.index, name=f"parkinson_{window}")
