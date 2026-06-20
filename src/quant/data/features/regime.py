"""Regime features (Deep Dive #1 §2.2.G).

*"Trend vs range classification, volatility regime (from an HMM/GMM — detailed in Deep
Dive #2/#3), index-level state. Used to gate strategies on/off."*

This module provides the lightweight, model-free regime descriptors used as model inputs;
the HMM/GMM regime *gate* itself is Layer-2/3 work. Both features are causal (trailing
windows only), so they are point-in-time correct.
"""

import pandas as pd

from quant.data.features.volatility import realized_volatility


def volatility_regime(bars: pd.DataFrame, *, vol_window: int, lookback: int) -> pd.Series:
    """Return current realized volatility relative to its trailing median (a regime ratio).

    ``rvol_t / median(rvol)_{trailing lookback}``: values ``> 1`` mark a high-volatility
    regime, ``< 1`` a calm one. Both the vol and its median use trailing windows.

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        vol_window: Realized-volatility window in bars (> 1).
        lookback: Trailing window for the volatility median in bars (> 1).

    Raises:
        ValueError: If ``vol_window`` or ``lookback`` is not greater than 1.
    """
    if lookback <= 1:
        raise ValueError(f"lookback must be > 1, got {lookback!r}")
    rvol = realized_volatility(bars, vol_window)  # validates vol_window
    median = rvol.rolling(lookback).median()
    return (rvol / median.where(median != 0)).rename("vol_regime")


def trend_strength(bars: pd.DataFrame, *, window: int) -> pd.Series:
    """Return a trend/range descriptor: the z-score of close vs its trailing mean.

    ``(close - rolling_mean) / rolling_std``: large positive/negative values indicate a
    trending move away from the recent average, values near zero indicate ranging. Causal
    (trailing window only).

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        window: Trailing window in bars (> 1).

    Raises:
        ValueError: If ``window`` is not greater than 1.
    """
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window!r}")
    close = bars["close"]
    mean = close.rolling(window).mean()
    std = close.rolling(window).std()
    return ((close - mean) / std.where(std != 0)).rename("trend_strength")
