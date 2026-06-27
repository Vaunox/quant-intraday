"""Tests for the event-reaction recorder (Part VI / P9.2) on a fake bars repository."""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.data.recorders.errors import EventRecorderError
from quant.data.recorders.events import (
    EarningsEvent,
    EventReactionRecorder,
    ParquetEventReactionStore,
)


class _FakeRepo:
    """A Repository stub serving a single symbol's synthetic daily closes."""

    def __init__(self, closes: pd.DataFrame) -> None:
        self._bars = closes

    def write_bars(self, symbol: str, bars: pd.DataFrame) -> None:  # pragma: no cover - unused
        raise NotImplementedError

    def read_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        mask = (self._bars["timestamp"] >= start) & (self._bars["timestamp"] <= end)
        return self._bars[mask].reset_index(drop=True)


def _daily_bars(symbol: str, n: int, jump_at: int, jump: float) -> pd.DataFrame:
    """Synthetic daily bars with a one-day jump at ``jump_at`` followed by continued drift."""
    dates = pd.date_range("2026-01-01", periods=n, freq="B", tz=IST)
    close = np.full(n, 100.0)
    close[jump_at:] *= 1.0 + jump  # the announcement reaction
    close[jump_at + 1 :] *= 1.0 + jump * 0.3  # post-announcement drift in the same direction
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000,
        }
    )


def test_surprise_sign_and_scale() -> None:
    pos = EarningsEvent("ACME", datetime(2026, 3, 1, tzinfo=IST), actual=11.0, estimate=10.0)
    assert pos.surprise == pytest.approx(0.1)
    zero_est = EarningsEvent("ACME", datetime(2026, 3, 1, tzinfo=IST), actual=5.0, estimate=0.0)
    assert zero_est.surprise == 1.0  # direction only when scale is undefined


def test_recorder_computes_reaction_and_drift() -> None:
    bars = _daily_bars("ACME", n=60, jump_at=30, jump=0.05)
    repo = _FakeRepo(bars)
    recorder = EventReactionRecorder(repo, pre_days=5, reaction_days=1, drift_days=10)  # type: ignore[arg-type]
    # Announce at the close of bar 29 -> anchor=29, reaction into bar 30 (the +5% jump).
    event_time = bars["timestamp"].iloc[29]
    event = EarningsEvent("ACME", event_time.to_pydatetime(), actual=12.0, estimate=10.0)
    records = recorder.record([event])
    assert len(records) == 1
    rec = records[0]
    assert rec.reaction_return == pytest.approx(0.05, abs=1e-9)  # the announcement jump
    assert rec.drift_return > 0.0  # continued drift in the surprise direction
    assert rec.surprise == pytest.approx(0.2)


def test_recorder_skips_events_without_enough_history() -> None:
    bars = _daily_bars("ACME", n=20, jump_at=10, jump=0.03)
    repo = _FakeRepo(bars)
    recorder = EventReactionRecorder(repo, pre_days=5, reaction_days=1, drift_days=20)  # type: ignore[arg-type]
    # Event near the very end -> drift window runs off the data -> skipped.
    event_time = bars["timestamp"].iloc[18]
    event = EarningsEvent("ACME", event_time.to_pydatetime(), actual=11.0, estimate=10.0)
    assert recorder.record([event]) == []


def test_recorder_rejects_bad_horizons() -> None:
    with pytest.raises(EventRecorderError, match="must all be positive"):
        EventReactionRecorder(_FakeRepo(pd.DataFrame()), drift_days=0)  # type: ignore[arg-type]


def test_store_round_trip_and_idempotent(tmp_path: Path) -> None:
    bars = _daily_bars("ACME", n=60, jump_at=30, jump=0.05)
    repo = _FakeRepo(bars)
    recorder = EventReactionRecorder(repo, pre_days=5, reaction_days=1, drift_days=10)  # type: ignore[arg-type]
    event = EarningsEvent(
        "ACME", bars["timestamp"].iloc[29].to_pydatetime(), actual=12.0, estimate=10.0
    )
    records = recorder.record([event])
    store = ParquetEventReactionStore(tmp_path)
    assert store.write(records) == 1
    assert store.write(records) == 1  # idempotent: same (symbol, event_time) merges
    out = store.read()
    assert len(out) == 1
    assert set(out.columns) >= {"symbol", "surprise", "reaction_return", "drift_return"}
