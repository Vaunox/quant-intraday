"""Tests for microstructure / order-flow features (P1.7)."""

from datetime import date

import pandas as pd
import pytest

from quant.core.types import DepthLevel, DepthSnapshot, Tick
from quant.data.features.microstructure import (
    DEPTH_COLUMNS,
    bid_ask_spread,
    depth_imbalance,
    depth_to_frame,
    order_flow_imbalance,
    relative_spread,
    signed_volume,
    trades_to_frame,
)
from tests.unit.hygiene_fakes import at

D1 = date(2024, 6, 3)


def _snapshot(
    ts_minute: int, bids: list[tuple[float, int]], asks: list[tuple[float, int]]
) -> DepthSnapshot:
    return DepthSnapshot(
        symbol="X",
        timestamp=at(D1, 9, ts_minute),
        bids=tuple(DepthLevel(price=p, quantity=q, orders=1) for p, q in bids),
        asks=tuple(DepthLevel(price=p, quantity=q, orders=1) for p, q in asks),
    )


def test_depth_to_frame_layout_and_missing_levels() -> None:
    frame = depth_to_frame([_snapshot(15, [(100.0, 10)], [(101.0, 20)])])
    assert tuple(frame.columns) == DEPTH_COLUMNS
    assert frame["bid_price_1"].iloc[0] == 100.0
    assert frame["bid_qty_1"].iloc[0] == 10
    assert frame["ask_price_1"].iloc[0] == 101.0
    assert pd.isna(frame["bid_price_2"].iloc[0])  # missing level -> NaN price
    assert frame["bid_qty_2"].iloc[0] == 0  # ... and zero qty


def test_spread_and_relative_spread() -> None:
    frame = depth_to_frame([_snapshot(15, [(100.0, 10)], [(101.0, 20)])])
    assert bid_ask_spread(frame).iloc[0] == pytest.approx(1.0)
    # rel spread = (1 / 100.5) * 1e4 bps
    assert relative_spread(frame).iloc[0] == pytest.approx(1.0 / 100.5 * 1e4)


def test_depth_imbalance_signs_with_bid_pressure() -> None:
    frame = depth_to_frame([_snapshot(15, [(100.0, 80)], [(101.0, 20)])])
    # (80 - 20) / (80 + 20) = 0.6
    assert depth_imbalance(frame).iloc[0] == pytest.approx(0.6)


def test_depth_imbalance_empty_book_is_nan() -> None:
    frame = depth_to_frame([_snapshot(15, [], [])])
    assert pd.isna(depth_imbalance(frame).iloc[0])


def test_ofi_best_level_size_increase() -> None:
    # Bid price unchanged, size 10 -> 15 (added bid depth = +5 buying pressure); ask flat.
    snapshots = [
        _snapshot(15, [(100.0, 10)], [(101.0, 20)]),
        _snapshot(16, [(100.0, 15)], [(101.0, 20)]),
    ]
    ofi = order_flow_imbalance(depth_to_frame(snapshots))
    assert pd.isna(ofi.iloc[0])  # no predecessor
    assert ofi.iloc[1] == pytest.approx(5.0)


def test_ofi_bid_price_up_adds_full_size() -> None:
    snapshots = [
        _snapshot(15, [(100.0, 10)], [(101.0, 20)]),
        _snapshot(16, [(101.0, 12)], [(102.0, 20)]),  # bid up, ask up
    ]
    ofi = order_flow_imbalance(depth_to_frame(snapshots))
    # e_bid: bid price up -> +qbid_t = 12. e_ask: ask price up -> -qask_{t-1} = -20.
    # OFI = e_bid - e_ask = 12 - (-20) = 32.
    assert ofi.iloc[1] == pytest.approx(32.0)


def test_ofi_rejects_bad_levels() -> None:
    frame = depth_to_frame([_snapshot(15, [(100.0, 10)], [(101.0, 20)])])
    with pytest.raises(ValueError, match="levels"):
        order_flow_imbalance(frame, levels=6)


def test_signed_volume_tick_rule() -> None:
    ticks = [
        Tick(symbol="X", timestamp=at(D1, 9, 15 + i), last_price=p, last_quantity=10, volume=0)
        for i, p in enumerate([100.0, 101.0, 101.0, 100.0, 102.0])
    ]
    result = signed_volume(trades_to_frame(ticks))
    # diffs -> signs [nan,+,0->carry +,-,+]; *qty(10)
    assert result.tolist() == [0.0, 10.0, 10.0, -10.0, 10.0]


def test_signed_volume_empty() -> None:
    assert signed_volume(trades_to_frame([])).empty
