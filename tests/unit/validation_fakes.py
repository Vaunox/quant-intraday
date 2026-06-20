"""Shared builders for the validation-harness unit tests (P2.1).

Small helpers to construct canonical bars frames (with explicit open/close so a backtest's
fills and mark-to-market are exactly hand-checkable), label-time series for the purged CV,
target-position series, and zero/flat cost & slippage models for isolating fill mechanics.
Not a ``test_*`` module, so pytest does not collect it; imported by the validation tests.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from quant.core.config import CostConfig, SlippageConfig
from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.slippage import DepthAwareSlippage

IST = ZoneInfo("Asia/Kolkata")


def at(day: date, hour: int = 9, minute: int = 15) -> datetime:
    """Return an IST instant on ``day`` at ``hour:minute``."""
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


def session_bars(
    day: date,
    opens: Sequence[float],
    *,
    closes: Sequence[float] | None = None,
    volume: int = 10_000,
    start_hour: int = 9,
    start_minute: int = 15,
    step_minutes: int = 15,
) -> pd.DataFrame:
    """Build a one-session bars frame from per-bar open (and optional close) prices.

    Bars are spaced ``step_minutes`` apart from ``start``. ``closes`` defaults to
    ``opens`` (flat bars). High/low bracket the open/close so the schema is valid.
    """
    closes = list(opens) if closes is None else list(closes)
    first = datetime.combine(day, time(start_hour, start_minute), tzinfo=IST)
    bars = []
    for i, (o, c) in enumerate(zip(opens, closes, strict=True)):
        ts = first + timedelta(minutes=step_minutes * i)
        bars.append(
            Bar("X", ts, open=o, high=max(o, c) + 1.0, low=min(o, c) - 1.0, close=c, volume=volume)
        )
    return bars_to_frame(bars)


def targets(mapping: Mapping[datetime, int]) -> pd.Series:
    """Build a signed-share target-position Series indexed by decision timestamp."""
    index = pd.DatetimeIndex(list(mapping.keys()))
    return pd.Series(list(mapping.values()), index=index, dtype="int64")


def label_times(pairs: Sequence[tuple[datetime, datetime]]) -> pd.Series:
    """Build a ``label_times`` Series: index = event time ``t0``, value = resolution ``t1``."""
    starts = pd.DatetimeIndex([t0 for t0, _ in pairs])
    ends = [t1 for _, t1 in pairs]
    return pd.Series(ends, index=starts)


def overlapping_label_times(
    n: int, *, span_steps: int = 2, day_step: int = 1, base: datetime | None = None
) -> pd.Series:
    """``n`` events one ``day_step`` apart, each label spanning ``span_steps`` forward.

    Adjacent windows overlap (the realistic, leakage-prone case the purge must handle).
    """
    base = datetime(2024, 1, 1, 9, 15, tzinfo=IST) if base is None else base
    pairs = [
        (base + timedelta(days=i * day_step), base + timedelta(days=(i + span_steps) * day_step))
        for i in range(n)
    ]
    return label_times(pairs)


def zero_cost_model() -> IndianCostModel:
    """A cost model with every rate zeroed (isolates fill/price mechanics)."""
    return IndianCostModel(
        CostConfig(
            brokerage_rate=0.0,
            brokerage_cap_inr=0.0,
            stt_sell_rate=0.0,
            exchange_txn_rate=0.0,
            stamp_duty_buy_rate=0.0,
            gst_rate=0.0,
            sebi_charges_rate=0.0,
        )
    )


def flat_slippage(bps: float) -> DepthAwareSlippage:
    """A slippage model with a constant ``bps`` (min == max), independent of size."""
    return DepthAwareSlippage(SlippageConfig(model="flat", min_bps=bps, max_bps=bps))


def zero_slippage() -> DepthAwareSlippage:
    """A slippage model that never moves the price."""
    return flat_slippage(0.0)
