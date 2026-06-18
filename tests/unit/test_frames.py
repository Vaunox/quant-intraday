"""Tests for the bars <-> DataFrame bridge (P0.5 hybrid contracts)."""

from datetime import UTC, datetime

from quant.core.frames import BAR_COLUMNS, bars_to_frame, frame_to_bars
from quant.core.types import Bar

NOW = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
LATER = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)


def test_schema_pins_expected_columns() -> None:
    # If Bar's fields change, this fails deliberately so the schema gets reviewed.
    assert BAR_COLUMNS == ("symbol", "timestamp", "open", "high", "low", "close", "volume")


def test_bars_to_frame_shape() -> None:
    frame = bars_to_frame([Bar("X", NOW, 1.0, 2.0, 0.5, 1.5, 100)])
    assert list(frame.columns) == list(BAR_COLUMNS)
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 1.5


def test_roundtrip_preserves_bars() -> None:
    bars = [
        Bar("X", NOW, 1.0, 2.0, 0.5, 1.5, 100),
        Bar("X", LATER, 1.5, 2.5, 1.0, 2.0, 200),
    ]
    assert frame_to_bars(bars_to_frame(bars)) == bars


def test_empty_roundtrip() -> None:
    assert frame_to_bars(bars_to_frame([])) == []
