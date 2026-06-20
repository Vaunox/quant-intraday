"""Time-of-day / seasonality features (Deep Dive #1 §2.2.E).

*"Minute-of-day, time-since-open, time-to-close, day-of-week. Intraday markets have
strong, exploitable diurnal patterns (open volatility, lunch lull, close auction
pressure). Encode cyclically (sin/cos) rather than as raw integers."*

Cyclical encoding maps a periodic quantity onto the unit circle so that, e.g., the last
minute of the day is adjacent to the first — a model never sees a false discontinuity at
the wrap-around. These features are pure, deterministic functions of the (tz-aware) bar
timestamp, so they are trivially point-in-time correct.
"""

import numpy as np
import pandas as pd

from quant.core.calendar import IST, NSECalendar

#: Output columns of :func:`time_of_day_features`, in order.
TEMPORAL_COLUMNS: tuple[str, ...] = (
    "minute_of_day_sin",
    "minute_of_day_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "time_since_open",
    "time_to_close",
)

_MINUTES_PER_DAY = 24 * 60
_DAYS_PER_WEEK = 7


def time_of_day_features(bars: pd.DataFrame, calendar: NSECalendar) -> pd.DataFrame:
    """Return the cyclical time-of-day feature frame for ``bars``.

    Columns (see :data:`TEMPORAL_COLUMNS`): sin/cos of minute-of-day and day-of-week, and
    the within-session fractions ``time_since_open`` / ``time_to_close`` in ``[0, 1]``
    (computed from the NSE session bounds for each bar's IST date).

    Args:
        bars: A canonical-schema bars DataFrame (tz-aware timestamps).
        calendar: NSE calendar providing each day's session open/close.

    Returns:
        A DataFrame indexed by bar timestamp with the temporal feature columns.
    """
    timestamps = pd.DatetimeIndex(bars["timestamp"]).tz_convert(IST)
    minute_of_day = timestamps.hour * 60 + timestamps.minute
    day_of_week = timestamps.dayofweek

    minute_angle = 2.0 * np.pi * minute_of_day / _MINUTES_PER_DAY
    week_angle = 2.0 * np.pi * day_of_week / _DAYS_PER_WEEK
    since, to_close = _session_fractions(timestamps, calendar)

    result = pd.DataFrame(
        {
            "minute_of_day_sin": np.sin(minute_angle),
            "minute_of_day_cos": np.cos(minute_angle),
            "day_of_week_sin": np.sin(week_angle),
            "day_of_week_cos": np.cos(week_angle),
            "time_since_open": since,
            "time_to_close": to_close,
        },
        index=pd.DatetimeIndex(bars["timestamp"], name="timestamp"),
    )
    return result


def _session_fractions(
    timestamps: pd.DatetimeIndex, calendar: NSECalendar
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(time_since_open, time_to_close)`` as session fractions in ``[0, 1]``."""
    since = np.empty(len(timestamps), dtype="float64")
    to_close = np.empty(len(timestamps), dtype="float64")
    for i, moment in enumerate(timestamps):
        open_at = calendar.session_open(moment.date())
        close_at = calendar.session_close(moment.date())
        span = (close_at - open_at).total_seconds()
        elapsed = (moment - open_at).total_seconds()
        since[i] = elapsed / span
        to_close[i] = (close_at - moment).total_seconds() / span
    return since, to_close
