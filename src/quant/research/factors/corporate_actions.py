"""Split/bonus back-adjustment of the daily panel for the factor pipeline (P3X.1e).

Bhavcopy is raw, so a split or bonus shows up as a large fake overnight drop (a 1:2 split looks like
-50%) that would wreck momentum / reversal / vol. The fix must *not* be a blanket clip of extreme
returns — that would also erase the **real** crashes of delisted names, which are the whole point of
a survivorship-correct universe.

So this uses the NSE corporate-actions feed only to learn *which* (symbol, ex-date) pairs are
splits/bonuses, then back-adjusts each using the **observed** overnight price ratio at that ex-date.
Confirmed corporate-action days are adjusted exactly; every other day — including genuine crashes —
is left untouched.
"""

from collections.abc import Iterable
from datetime import date

import pandas as pd

from quant.research.factors.errors import FactorError

#: An ex-date as it may arrive from a CSV / feed (ISO/NSE string, ``date``, or ``Timestamp``).
ExDate = str | date | pd.Timestamp


def back_adjust_for_splits(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    events: Iterable[tuple[str, ExDate]],
    *,
    max_factor: float = 0.98,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Back-adjust ``close`` and ``volume`` for the given split/bonus ex-dates.

    For each confirmed ``(symbol, ex_date)``, the per-event factor is the observed
    ``close[ex] / close[ex-1]`` (≈ 1/split-ratio); all prices strictly before the ex-date are
    multiplied by it (volume divided), so the series is continuous. A day whose observed ratio is
    not a real drop (``>= max_factor``, e.g. an ex-date misaligned by one session) is skipped rather
    than risk corrupting the series.

    Args:
        close: ``date x symbol`` close panel (raw bhavcopy).
        volume: ``date x symbol`` volume panel, same index/columns as ``close``.
        events: confirmed split/bonus ``(symbol, ex_date)`` pairs from the NSE CA feed.
        max_factor: only adjust when the observed ratio is below this (a genuine downward jump).

    Returns:
        ``(adjusted_close, adjusted_volume)`` — copies; inputs are untouched.

    Raises:
        FactorError: If ``close`` and ``volume`` are not aligned on the same index and columns.
    """
    if list(close.columns) != list(volume.columns) or not close.index.equals(volume.index):
        raise FactorError("close and volume panels must share the same index and columns")

    index = pd.DatetimeIndex(close.index)
    pos_by_date: dict[date, int] = {ts.date(): i for i, ts in enumerate(index)}

    grouped: dict[str, list[date]] = {}
    for symbol, ex in events:
        grouped.setdefault(str(symbol), []).append(pd.Timestamp(ex).date())

    adjusted_close = close.copy()
    adjusted_volume = volume.copy()
    for symbol, ex_dates in grouped.items():
        if symbol not in close.columns:
            continue
        raw = close[symbol].to_numpy(dtype="float64")
        col = raw.copy()
        vol = adjusted_volume[symbol].to_numpy(dtype="float64", copy=True)
        for ex_date in sorted(ex_dates):
            pos = pos_by_date.get(ex_date)
            if pos is None or pos == 0:
                continue
            prev, cur = raw[pos - 1], raw[pos]
            if not (prev > 0 and cur > 0):
                continue
            factor = cur / prev
            if not 0.0 < factor < max_factor:
                continue
            col[:pos] *= factor
            vol[:pos] /= factor
        adjusted_close[symbol] = col
        adjusted_volume[symbol] = vol
    return adjusted_close, adjusted_volume
