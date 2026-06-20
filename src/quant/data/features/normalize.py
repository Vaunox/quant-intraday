"""Feature normalization & winsorization (Deep Dive #1 §2.3).

*"Trailing/rolling normalization for time-series features — expanding or rolling window
only. Robust scaling (median/IQR) rather than mean/std where features are fat-tailed.
Winsorize extreme outliers (cap at e.g. 1st/99th rolling percentile)."*

The cardinal rule (§2.1): normalization statistics must come from a **trailing** window,
never the full sample — full-sample z-scoring leaks the future distribution into the past.
Every function here uses trailing rolling windows only, so it is point-in-time correct and
causal (the value at *t* depends only on bars at or before *t*).
"""

import pandas as pd


def winsorize(series: pd.Series, *, window: int, lower_pct: float, upper_pct: float) -> pd.Series:
    """Clip ``series`` to its trailing rolling ``[lower_pct, upper_pct]`` percentiles.

    A single bad print can dominate a fat-tailed feature; this caps it to the recent
    distribution (so it never silently mutates the value, only bounds it). Bounds are
    computed on a trailing window, so the result is point-in-time correct.

    Args:
        series: The feature series to winsorize.
        window: Trailing window length in bars (must be > 1).
        lower_pct: Lower percentile in ``[0, 100)`` (e.g. ``1.0``).
        upper_pct: Upper percentile in ``(0, 100]`` (e.g. ``99.0``); must exceed ``lower_pct``.

    Raises:
        ValueError: If ``window <= 1`` or the percentiles are out of range/order.
    """
    _validate_window(window)
    if not 0.0 <= lower_pct < upper_pct <= 100.0:
        raise ValueError(f"require 0 <= lower_pct < upper_pct <= 100, got {lower_pct}, {upper_pct}")
    lower = series.rolling(window).quantile(lower_pct / 100.0)
    upper = series.rolling(window).quantile(upper_pct / 100.0)
    return series.clip(lower=lower, upper=upper)  # clip preserves the series name


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Return the trailing rolling z-score: ``(x - rolling_mean) / rolling_std``.

    Raises:
        ValueError: If ``window <= 1``.
    """
    _validate_window(window)
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std.where(std != 0)  # arithmetic preserves the series name


def robust_zscore(series: pd.Series, window: int) -> pd.Series:
    """Return the trailing robust z-score: ``(x - rolling_median) / rolling_IQR``.

    Uses median/IQR rather than mean/std, so a fat tail or a single outlier in the
    window does not blow up the scale (Deep Dive #1 §2.3). Where the IQR is zero (a flat
    window) the result is ``NaN`` rather than a divide-by-zero.

    Raises:
        ValueError: If ``window <= 1``.
    """
    _validate_window(window)
    median = series.rolling(window).median()
    q1 = series.rolling(window).quantile(0.25)
    q3 = series.rolling(window).quantile(0.75)
    iqr = q3 - q1
    return (series - median) / iqr.where(iqr != 0)  # arithmetic preserves the series name


def _validate_window(window: int) -> None:
    """Raise if ``window`` is not greater than 1 (a 1-bar window has no dispersion)."""
    if window <= 1:
        raise ValueError(f"window must be > 1, got {window!r}")
