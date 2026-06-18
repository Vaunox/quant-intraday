"""Tests for shared domain types (P0.5)."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from quant.core.types import (
    Bar,
    DepthLevel,
    DepthSnapshot,
    Margins,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Side,
    Signal,
)

NOW = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


def test_bar_fields() -> None:
    bar = Bar(symbol="X", timestamp=NOW, open=1.0, high=2.0, low=0.5, close=1.5, volume=100)
    assert bar.symbol == "X"
    assert bar.close == 1.5
    assert bar.volume == 100


def test_depth_best_levels() -> None:
    snap = DepthSnapshot(
        symbol="X",
        timestamp=NOW,
        bids=(DepthLevel(99.0, 10, 2), DepthLevel(98.0, 5, 1)),
        asks=(DepthLevel(101.0, 8, 3),),
    )
    assert snap.best_bid is not None
    assert snap.best_bid.price == 99.0
    assert snap.best_ask is not None
    assert snap.best_ask.price == 101.0


def test_depth_empty_side() -> None:
    snap = DepthSnapshot(symbol="X", timestamp=NOW, bids=(), asks=())
    assert snap.best_bid is None
    assert snap.best_ask is None


def test_order_request_defaults() -> None:
    req = OrderRequest(symbol="X", side=Side.BUY, quantity=10, order_type=OrderType.MARKET)
    assert req.product is Product.MIS
    assert req.price is None
    assert req.client_order_id is None


def test_order_fill_properties() -> None:
    partial = Order(
        order_id="O1",
        symbol="X",
        side=Side.BUY,
        quantity=10,
        filled_quantity=4,
        order_type=OrderType.LIMIT,
        product=Product.MIS,
        status=OrderStatus.OPEN,
    )
    assert not partial.is_complete
    assert partial.remaining_quantity == 6

    done = Order(
        order_id="O2",
        symbol="X",
        side=Side.BUY,
        quantity=10,
        filled_quantity=10,
        order_type=OrderType.LIMIT,
        product=Product.MIS,
        status=OrderStatus.COMPLETE,
    )
    assert done.is_complete
    assert done.remaining_quantity == 0


def test_position_side_and_flat() -> None:
    assert Position("X", 5, 100.0).side is Side.BUY
    assert Position("X", -5, 100.0).side is Side.SELL
    flat = Position("X", 0, 0.0)
    assert flat.is_flat
    assert flat.side is None


def test_signal() -> None:
    sig = Signal(symbol="X", asof=NOW, side=Side.SELL, strength=0.8)
    assert sig.side is Side.SELL
    assert sig.strength == 0.8


def test_enum_values() -> None:
    assert Side.BUY.value == "buy"
    assert OrderType.SL_M.value == "sl_m"
    assert OrderStatus.PENDING_RECEIVED.value == "put_order_req_received"


def test_types_are_immutable() -> None:
    bar = Bar(symbol="X", timestamp=NOW, open=1.0, high=2.0, low=0.5, close=1.5, volume=100)
    with pytest.raises(FrozenInstanceError):
        bar.close = 2.0  # type: ignore[misc]


def test_margins() -> None:
    margins = Margins(
        available_cash=50_000.0, available_margin=80_000.0, used_margin=20_000.0, net=100_000.0
    )
    assert margins.available_cash == 50_000.0
    assert margins.used_margin == 20_000.0
    assert margins.net == 100_000.0
