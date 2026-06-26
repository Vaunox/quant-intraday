"""Shared barrier-scan primitives for the primary and meta labelers (P2.3 / P2.5).

The triple-barrier (primary) labeler and the meta (bet/no-bet) labeler both resolve an
event by walking its forward price path and recording which horizontal barrier the path
touches first — with the **conservative same-bar rule**: when one bar gaps through both
barriers the intrabar order is unknown, so the *stop* side wins (the non-fantasy choice).
That logic, and the event→position / volatility-alignment / session-end helpers, live here
once so the two labelers can never diverge on a correctness-critical invariant
(Ground Rule 4).
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.calendar import IST
from quant.research.labeling.errors import LabelingInputError

#: First-touch outcomes: which barrier (or the vertical) the forward path reached first.
TOUCH_HIGH = "high"
TOUCH_LOW = "low"
TOUCH_VERTICAL = "vertical"


def first_touch(
    high: npt.NDArray[np.float64],
    low: npt.NDArray[np.float64],
    position: int,
    vertical: int,
    *,
    high_barrier: float,
    low_barrier: float,
    tie_to_low: bool,
) -> tuple[str, int]:
    """Return ``(touched, exit_position)`` for the first barrier the path reaches.

    Scans bars ``position+1 .. vertical`` (inclusive). A bar touches the high barrier when
    ``high >= high_barrier`` and the low barrier when ``low <= low_barrier``. On a same-bar
    breach of both, the stop side wins: the low barrier if ``tie_to_low`` else the high.
    If neither is touched, the vertical barrier resolves it.
    """
    for pos in range(position + 1, vertical + 1):
        hit_high = high[pos] >= high_barrier
        hit_low = low[pos] <= low_barrier
        if hit_high and hit_low:
            return (TOUCH_LOW, pos) if tie_to_low else (TOUCH_HIGH, pos)
        if hit_high:
            return TOUCH_HIGH, pos
        if hit_low:
            return TOUCH_LOW, pos
    return TOUCH_VERTICAL, vertical


def vertical_position(position: int, session_last: int, max_hold: int) -> int:
    """The vertical-barrier bar position: session end, optionally capped to ``max_hold`` bars."""
    vertical = int(session_last)
    if max_hold > 0:
        vertical = min(vertical, position + max_hold)
    return vertical


def session_last_position(times: pd.DatetimeIndex) -> npt.NDArray[np.intp]:
    """For each bar, the position of the last bar in its IST session (the vertical barrier)."""
    session = np.asarray(times.tz_convert(IST).date, dtype="object")
    n = session.shape[0]
    last = np.empty(n, dtype=np.intp)
    boundary = n - 1
    for i in range(n - 1, -1, -1):
        if i == n - 1 or session[i] != session[i + 1]:
            boundary = i
        last[i] = boundary
    return last


def vertical_anchor_positions(
    times: pd.DatetimeIndex, *, holding_mode: str = "mis"
) -> npt.NDArray[np.intp]:
    """Per-bar anchor that :func:`vertical_position` clamps the vertical barrier to.

    The two holding modes differ only in what bounds the hold:

    * ``"mis"`` (intraday, default) — the anchor is the last bar of each bar's **IST session**,
      so the vertical barrier never crosses a session boundary (overnight square-off). Original,
      unchanged behaviour (delegates to :func:`session_last_position`).
    * ``"cnc"`` (delivery / multi-day) — the anchor is the **final bar of the series**, so
      :func:`vertical_position` resolves the vertical barrier to ``event + max_hold`` bars
      *across* session boundaries (an overnight/multi-day hold). Only meaningful with a positive
      ``max_hold``; with ``max_hold == 0`` it degenerates to "hold to the series end".

    Args:
        times: The (sorted, unique, tz-aware) bar timeline.
        holding_mode: ``"mis"`` or ``"cnc"``.

    Raises:
        LabelingInputError: If ``holding_mode`` is neither ``"mis"`` nor ``"cnc"``.
    """
    if holding_mode == "mis":
        return session_last_position(times)
    if holding_mode == "cnc":
        n = times.shape[0]
        return np.full(n, max(n - 1, 0), dtype=np.intp)
    raise LabelingInputError(f"unknown holding_mode {holding_mode!r} (expected 'mis' or 'cnc')")


def event_positions(events: pd.DatetimeIndex, times: pd.DatetimeIndex) -> list[int]:
    """Map event timestamps to bar positions (sorted, de-duped), failing loud on an unknown."""
    if not isinstance(events, pd.DatetimeIndex):
        raise LabelingInputError(f"events must be a DatetimeIndex, got {type(events)}")
    locations = times.get_indexer(events)
    if (locations < 0).any():
        raise LabelingInputError("every event must correspond to a bar timestamp")
    return sorted({int(loc) for loc in locations})


def aligned_volatility(volatility: pd.Series, times: pd.DatetimeIndex) -> npt.NDArray[np.float64]:
    """Reindex the volatility Series onto the bar timeline (NaN where absent)."""
    if not isinstance(volatility.index, pd.DatetimeIndex):
        raise LabelingInputError("volatility must be indexed by bar timestamp (DatetimeIndex)")
    return volatility.reindex(times).to_numpy(dtype="float64")
