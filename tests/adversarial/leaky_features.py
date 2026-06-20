"""Intentionally-leaky features — the known-bad inputs the tripwires must catch (P1.8).

These deliberately violate point-in-time correctness. The adversarial tests assert that
the structural checks in :mod:`tests.adversarial.leakage` raise on each of them, proving
the suite would fail CI if such a feature ever entered the real library. Not collected.
"""

import pandas as pd


def lookahead_return(bars: pd.DataFrame) -> pd.Series:
    """LEAKY: uses the *next* bar's close (``shift(-1)``) — peeks one bar into the future."""
    close = bars["close"]
    return (close.shift(-1) / close - 1.0).rename("leaky_forward_return")


def centered_volatility(bars: pd.DataFrame) -> pd.Series:
    """LEAKY: a *centred* rolling window straddles future bars."""
    return bars["close"].rolling(5, center=True).std().rename("leaky_centered_vol")


def full_sample_zscore(series: pd.Series) -> pd.Series:
    """LEAKY normalizer: standardizes by the *full-sample* mean/std (leaks the distribution)."""
    return (series - series.mean()) / series.std()
