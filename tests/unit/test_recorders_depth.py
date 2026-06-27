"""Tests for the live-depth recorder (Part VI / P9.1) — round-trip, idempotency, bounded buffer."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from quant.core.calendar import IST
from quant.core.types import DepthLevel, DepthSnapshot, MarketUpdate, Tick
from quant.data.recorders.depth import DepthRecorder, DepthSnapshotArchive, depth_snapshot_to_row
from quant.data.recorders.errors import DepthRecorderError

_T0 = datetime(2026, 6, 1, 9, 15, tzinfo=IST)


def _snapshot(symbol: str, ts: datetime, levels: int = 5) -> DepthSnapshot:
    bids = tuple(
        DepthLevel(price=100.0 - i, quantity=10 * (i + 1), orders=i + 1) for i in range(levels)
    )
    asks = tuple(
        DepthLevel(price=101.0 + i, quantity=12 * (i + 1), orders=i + 2) for i in range(levels)
    )
    return DepthSnapshot(symbol=symbol, timestamp=ts, bids=bids, asks=asks)


def _update(symbol: str, ts: datetime, *, depth: bool = True) -> MarketUpdate:
    tick = Tick(symbol=symbol, timestamp=ts, last_price=100.5, last_quantity=1, volume=100)
    snap = _snapshot(symbol, ts) if depth else None
    return MarketUpdate(tick=tick, depth=snap)


def test_flatten_row_has_fixed_schema_and_fills_missing_levels() -> None:
    row = depth_snapshot_to_row(_snapshot("ACME", _T0, levels=2))
    assert row["symbol"] == "ACME"
    assert row["bid_px_1"] == 100.0 and row["bid_qty_1"] == 10
    # Level 3 absent -> NaN price, 0 qty/orders.
    assert row["bid_qty_3"] == 0 and row["ask_ord_5"] == 0


def test_flatten_rejects_naive_timestamp() -> None:
    naive = DepthSnapshot(symbol="X", timestamp=datetime(2026, 6, 1, 9, 15), bids=(), asks=())
    with pytest.raises(DepthRecorderError, match="tz-aware"):
        depth_snapshot_to_row(naive)


def test_archive_round_trip(tmp_path: Path) -> None:
    archive = DepthSnapshotArchive(tmp_path)
    snaps = [_snapshot("ACME", _T0 + timedelta(seconds=i)) for i in range(3)]
    assert archive.write(snaps) == 3
    out = archive.read("ACME", _T0.date(), _T0.date())
    assert len(out) == 3
    assert list(out["bid_px_1"]) == [100.0, 100.0, 100.0]


def test_archive_write_is_idempotent(tmp_path: Path) -> None:
    archive = DepthSnapshotArchive(tmp_path)
    snaps = [_snapshot("ACME", _T0 + timedelta(seconds=i)) for i in range(3)]
    archive.write(snaps)
    archive.write(snaps)  # re-recording the same day must not duplicate rows
    assert len(archive.read("ACME", _T0.date(), _T0.date())) == 3


def test_recorder_auto_flushes_on_batch_and_ignores_depthless(tmp_path: Path) -> None:
    archive = DepthSnapshotArchive(tmp_path)
    recorder = DepthRecorder(archive, batch_size=2)
    recorder.record(_update("ACME", _T0))
    recorder.record(_update("ACME", _T0, depth=False))  # no depth -> ignored
    assert recorder.buffered == 1
    recorder.record(_update("ACME", _T0 + timedelta(seconds=1)))  # hits batch -> auto-flush
    assert recorder.buffered == 0 and recorder.recorded == 2


def test_recorder_flush_persists_tail(tmp_path: Path) -> None:
    archive = DepthSnapshotArchive(tmp_path)
    recorder = DepthRecorder(archive, batch_size=100)
    recorder.record_all(_update("ACME", _T0 + timedelta(seconds=i)) for i in range(5))
    assert recorder.buffered == 5
    assert recorder.flush() == 5
    assert len(archive.read("ACME", _T0.date(), _T0.date())) == 5


def test_recorder_rejects_bad_batch_size(tmp_path: Path) -> None:
    with pytest.raises(DepthRecorderError, match="batch_size must be positive"):
        DepthRecorder(DepthSnapshotArchive(tmp_path), batch_size=0)
