"""CUSUM event sampling (Deep Dive #2 §3.3).

*"Rather than evaluating an entry at every 15-min bar, use a CUSUM filter to trigger
candidate events only when cumulative price movement exceeds a threshold — i.e., sample
when something is happening."* This removes long stretches of dead, noisy bars, produces
more balanced labels, and reduces the dataset to meaningful decision points.

The **symmetric CUSUM filter** (López de Prado, *Advances in Financial ML* §2.5.2.1) keeps
two running sums of the per-bar log returns — one for up-moves, one for down-moves — each
floored/capped at zero. When either sum's magnitude reaches the threshold ``h`` a candidate
event is emitted at that bar and *that* accumulator resets, so each event marks a fresh
cumulative move rather than drift. The accumulators are inherently sequential, so this is a
single causal pass: an event at bar *t* depends only on returns at or before *t*.

The threshold may be a constant or a per-bar Series (e.g. a volatility-scaled ``h_t`` for a
non-stationary series). Increments are **log returns** (scale-invariant), so the threshold
is read in return units (``0.01`` ≈ a 1% cumulative move).
"""

import numpy as np
import pandas as pd

from quant.core.logging import get_logger
from quant.research.labeling.errors import LabelingInputError

_logger = get_logger(__name__)


def cusum_events(prices: pd.Series, threshold: float | pd.Series) -> pd.DatetimeIndex:
    """Return the timestamps where the symmetric CUSUM filter fires on ``prices``.

    Args:
        prices: A close-price Series indexed by tz-aware, sorted, unique timestamps
            (strictly positive prices).
        threshold: The CUSUM threshold ``h`` in return units — a positive scalar, or a
            per-bar Series aligned to ``prices`` (a dynamic, e.g. vol-scaled, threshold).

    Returns:
        A :class:`~pandas.DatetimeIndex` of candidate event times (a subset of
        ``prices.index``), in time order.

    Raises:
        LabelingInputError: If the index is not a sorted, unique, tz-aware
            ``DatetimeIndex``, any price is non-positive, a Series threshold is misaligned,
            or the threshold is not strictly positive.
    """
    if len(prices) == 0:
        return pd.DatetimeIndex([], name=prices.index.name)  # no data, nothing to sample
    _validate_prices(prices)
    increments = np.log(prices).diff()  # per-bar log returns; first entry is NaN
    threshold_at = _threshold_series(threshold, prices)

    s_up = 0.0
    s_down = 0.0
    events: list[pd.Timestamp] = []
    # Sequential single pass: the filter is stateful (accumulators carry across bars).
    for timestamp, increment in increments.items():
        if np.isnan(increment):
            continue  # the first bar has no return to accumulate
        limit = threshold_at[timestamp]
        s_up = max(0.0, s_up + float(increment))
        s_down = min(0.0, s_down + float(increment))
        if s_up >= limit:
            s_up = 0.0  # reset so the next event marks a fresh up-move, not drift
            events.append(timestamp)
        elif s_down <= -limit:
            s_down = 0.0
            events.append(timestamp)

    _logger.debug("cusum events sampled", extra={"bars": len(prices), "events": len(events)})
    return pd.DatetimeIndex(events, name=prices.index.name)


def _validate_prices(prices: pd.Series) -> None:
    """Validate the price-series contract (Ground Rule 7: fail loud at the boundary)."""
    index = prices.index
    if not isinstance(index, pd.DatetimeIndex):
        raise LabelingInputError(f"prices must have a DatetimeIndex, got {type(index)}")
    if index.tz is None:
        raise LabelingInputError("prices index must be timezone-aware (the system is IST)")
    if not index.is_monotonic_increasing:
        raise LabelingInputError("prices index must be sorted ascending")
    if not index.is_unique:
        raise LabelingInputError("prices index must be unique (one price per timestamp)")
    if len(prices) > 0 and not bool((prices.to_numpy() > 0).all()):
        raise LabelingInputError("prices must be strictly positive (log returns require it)")


def _threshold_series(threshold: float | pd.Series, prices: pd.Series) -> pd.Series:
    """Coerce ``threshold`` to a per-bar Series aligned to ``prices`` and validate it."""
    if isinstance(threshold, pd.Series):
        if not threshold.index.equals(prices.index):
            raise LabelingInputError("threshold Series must be indexed exactly like prices")
        if not bool((threshold.to_numpy() > 0).all()):
            raise LabelingInputError("every threshold value must be strictly positive")
        return threshold
    if threshold <= 0:
        raise LabelingInputError(f"threshold must be positive, got {threshold}")
    return pd.Series(threshold, index=prices.index)
