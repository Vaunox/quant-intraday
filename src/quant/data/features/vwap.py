"""VWAP-deviation feature (Deep Dive #1 §2.2.A — a workhorse intraday feature).

*"VWAP-to-mid deviation. Distance of price from intraday VWAP; short-horizon
asymmetries show transient pressure followed by mean-reversion as depth replenishes."*

Intraday VWAP is **cumulative within each session** (it resets each day), computed here
by grouping on the IST calendar date — no calendar dependency needed, since one IST date
is one session for intraday bars. Cumulative-within-day is causal (it uses only bars at
or before *t* within the day), so the feature is point-in-time correct (§2.1).
"""

import pandas as pd

from quant.core.calendar import IST
from quant.data.store import serde


def intraday_vwap(bars: pd.DataFrame) -> pd.Series:
    """Return the cumulative intraday VWAP (resets each IST session day).

    VWAP_t = cum(typical_price * volume) / cum(volume) within the bar's IST date, where
    typical price is ``(high + low + close) / 3``. Where cumulative volume is zero (a
    leading zero-volume bar) the VWAP is ``NaN`` rather than a divide-by-zero.
    """
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    day = bars[serde.TIME_COLUMN].dt.tz_convert(IST).dt.date
    cum_value = (typical * bars["volume"]).groupby(day).cumsum()
    cum_volume = bars["volume"].groupby(day).cumsum()
    # Leading zero cumulative volume -> NaN VWAP rather than a divide-by-zero.
    return (cum_value / cum_volume.where(cum_volume != 0)).rename("intraday_vwap")


def vwap_deviation(bars: pd.DataFrame) -> pd.Series:
    """Return the relative deviation of close from intraday VWAP: ``(close - vwap)/vwap``.

    Positive means price is above the session's volume-weighted average (recent buying
    pressure); negative means below. Causal/point-in-time by construction.
    """
    vwap = intraday_vwap(bars)
    return ((bars["close"] - vwap) / vwap).rename("vwap_dev")
