"""Price/return-transform features (Deep Dive #1 §2.2.B).

Multi-horizon log returns — the workhorse price transform. Every function here is a
**pure, causal** transform of a bars frame: the value at row *t* uses only bars at or
before *t* (via :meth:`~pandas.Series.shift`), so it is point-in-time correct by
construction (§2.1) and the vectorized output equals the incremental output bar-by-bar
(the dual-path guarantee in :mod:`quant.data.features.harness`).

Inputs are expected to be hygiene-clean, corporate-action *adjusted* bars (§1.3.2:
adjusted prices for return/feature computation; raw prices for fills).
"""

import numpy as np
import pandas as pd


def log_return(bars: pd.DataFrame, horizon: int) -> pd.Series:
    """Return the ``horizon``-bar log return of close, aligned to ``bars``.

    ``r_t = ln(close_t / close_{t-horizon})``; the first ``horizon`` rows are ``NaN``
    (insufficient history — correctly undefined at those points, never back-filled).

    Args:
        bars: A canonical-schema bars DataFrame (time-sorted).
        horizon: Lookback in bars (must be positive).

    Raises:
        ValueError: If ``horizon`` is not positive.
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be positive, got {horizon!r}")
    close = bars["close"]
    return pd.Series(np.log(close / close.shift(horizon)), index=bars.index, name=f"ret_{horizon}")
