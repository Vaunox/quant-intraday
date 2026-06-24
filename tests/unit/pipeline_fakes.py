"""Shared builders and fakes for the research-pipeline unit tests (P2A.6).

Synthetic minute bars (random-walk and flat), a small fast :class:`Config`, an in-memory
``Repository``, and a directly-constructed :class:`SymbolDataset` builder for the pooling tests.
Not a ``test_*`` module, so pytest does not collect it; imported by the pipeline tests.
"""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant.core.config import Config, load_config
from quant.core.frames import bars_to_frame
from quant.core.types import Bar
from quant.research.pipeline.dataset import REGIME_FEATURES, SymbolDataset

IST = ZoneInfo("Asia/Kolkata")
REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


def pipeline_config(**section_overrides: Any) -> Config:
    """A small, fast :class:`Config` for tests (short windows, few boosting rounds, 2 regimes)."""
    base = load_config(env="dev", environ={"QUANT_CONFIG_DIR": str(REPO_CONFIG)})
    features = base.features.model_copy(
        update={
            "return_horizons": (1, 3, 5),
            "volatility_window": 5,
            "atr_window": 5,
            "parkinson_window": 5,
            "regime_vol_window": 5,
            "regime_vol_lookback": 10,
            "trend_window": 5,
            "winsor_window": 10,
        }
    )
    model = base.model.model_copy(
        update={"num_boost_round": 20, "num_leaves": 7, "min_child_samples": 5, "cv_folds": 3}
    )
    labeling = base.labeling.model_copy(
        update={"cusum_threshold": 0.003, "barrier_min_return": 0.001}
    )
    pipeline = base.pipeline.model_copy(update={"pool_gap_days": 2, "n_regimes": 2})
    updates: dict[str, Any] = {
        "features": features,
        "model": model,
        "labeling": labeling,
        "pipeline": pipeline,
    }
    updates.update(section_overrides)
    return base.model_copy(update=updates)


def minute_bars(
    symbol: str,
    *,
    sessions: int,
    minutes: int = 120,
    seed: int = 0,
    drift: float = 0.0,
    vol: float = 0.0015,
    start_day: date = date(2024, 1, 1),
) -> pd.DataFrame:
    """Random-walk 1-minute bars over ``sessions`` weekday sessions (09:15 start)."""
    rng = np.random.default_rng(seed)
    bars: list[Bar] = []
    price = 100.0
    day = start_day
    placed = 0
    while placed < sessions:
        if day.weekday() < 5:  # weekday session
            ts = datetime.combine(day, time(9, 15), tzinfo=IST)
            for _ in range(minutes):
                new = price * (1.0 + float(rng.normal(drift, vol)))
                high = max(price, new) * (1.0 + abs(float(rng.normal(0, 0.0005))))
                low = min(price, new) * (1.0 - abs(float(rng.normal(0, 0.0005))))
                bars.append(Bar(symbol, ts, price, high, low, new, int(rng.integers(100, 1000))))
                price = new
                ts += timedelta(minutes=1)
            placed += 1
        day += timedelta(days=1)
    return bars_to_frame(bars)


def flat_bars(
    symbol: str,
    *,
    sessions: int,
    minutes: int = 60,
    price: float = 100.0,
    start_day: date = date(2024, 1, 1),
) -> pd.DataFrame:
    """Constant-price 1-minute bars (no CUSUM event ever fires)."""
    bars: list[Bar] = []
    day = start_day
    placed = 0
    while placed < sessions:
        if day.weekday() < 5:
            ts = datetime.combine(day, time(9, 15), tzinfo=IST)
            for _ in range(minutes):
                bars.append(Bar(symbol, ts, price, price, price, price, 100))
                ts += timedelta(minutes=1)
            placed += 1
        day += timedelta(days=1)
    return bars_to_frame(bars)


class FakeRepository:
    """A minimal in-memory ``Repository`` returning canned bars per symbol."""

    def __init__(self, bars: Mapping[str, pd.DataFrame]) -> None:
        self._bars = dict(bars)

    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self._bars.get(symbol, bars_to_frame([]))

    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:
        self._bars[symbol] = bars

    def list_symbols(self) -> list[str]:
        return list(self._bars)


def synthetic_symbol_dataset(
    symbol: str,
    n: int,
    *,
    seed: int = 0,
    start: datetime = datetime(2024, 1, 2, 9, 15, tzinfo=IST),
    step_minutes: int = 15,
    span_bars: int = 2,
    forward_loc: float = 0.0,
) -> SymbolDataset:
    """Build a :class:`SymbolDataset` directly (for pooling / gate tests; no feature pipeline).

    ``span_bars`` sets each label's ``t0 -> t1`` window length; ``forward_loc`` shifts the mean
    forward return (set it negative to drive a regime gate's edge non-positive).
    """
    rng = np.random.default_rng(seed)
    index = pd.DatetimeIndex(
        [start + timedelta(minutes=step_minutes * i) for i in range(n)], name="event_time"
    )
    features = pd.DataFrame(
        {"ret_1": rng.normal(size=n), "rvol_5": np.abs(rng.normal(1.0, 0.2, n))}, index=index
    )
    labels = pd.Series((rng.uniform(size=n) < 0.5).astype("int64"), index=index, name="label")
    label_times = pd.Series(
        [index[min(i + span_bars, n - 1)] for i in range(n)], index=index, name="t1"
    )
    forward = pd.Series(rng.normal(forward_loc, 0.01, size=n), index=index, name="forward_return")
    regime = pd.DataFrame(
        {
            REGIME_FEATURES[0]: np.abs(rng.normal(1.0, 0.3, n)),
            REGIME_FEATURES[1]: rng.normal(0.0, 1.0, n),
        },
        index=index,
    )
    weights = pd.Series(rng.uniform(0.5, 1.5, n), index=index, name="weight")
    return SymbolDataset(symbol, features, labels, label_times, forward, regime, weights)
