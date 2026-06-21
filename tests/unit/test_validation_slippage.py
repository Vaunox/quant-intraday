"""Tests for the size/depth-aware slippage model (P2.1, Deep Dive #2 §4b.6)."""

import pytest

from quant.core.config import SlippageConfig
from quant.core.types import Side
from quant.research.validation.slippage import DepthAwareSlippage

BAND = DepthAwareSlippage(SlippageConfig(model="depth_aware", min_bps=5.0, max_bps=20.0))


def test_floor_for_tiny_participation() -> None:
    # quantity / liquidity -> 0 gives the min_bps floor.
    assert BAND.slippage_bps(1, 10_000_000) == pytest.approx(5.0, abs=1e-3)


def test_ceiling_when_order_consumes_all_liquidity() -> None:
    assert BAND.slippage_bps(100, 100) == pytest.approx(20.0)  # participation == 1


def test_ceiling_when_order_exceeds_liquidity() -> None:
    assert BAND.slippage_bps(500, 100) == pytest.approx(20.0)  # clamped at participation 1


def test_linear_interpolation_with_participation() -> None:
    # participation = 0.5 -> halfway between floor and ceiling.
    assert BAND.slippage_bps(50, 100) == pytest.approx(5.0 + (20.0 - 5.0) * 0.5)


def test_no_liquidity_is_conservative_ceiling() -> None:
    assert BAND.slippage_bps(10, 0) == pytest.approx(20.0)
    assert BAND.slippage_bps(10, -5) == pytest.approx(20.0)


def test_monotonic_increasing_in_quantity() -> None:
    small = BAND.slippage_bps(10, 1000)
    large = BAND.slippage_bps(900, 1000)
    assert large > small


def test_buy_fills_above_reference() -> None:
    # participation 1 -> 20 bps = 0.20%.
    price = BAND.adjusted_fill_price(Side.BUY, 100.0, 100, 100)
    assert price == pytest.approx(100.0 * (1 + 20.0 / 1e4))


def test_sell_fills_below_reference() -> None:
    price = BAND.adjusted_fill_price(Side.SELL, 100.0, 100, 100)
    assert price == pytest.approx(100.0 * (1 - 20.0 / 1e4))


def test_flat_band_is_constant() -> None:
    flat = DepthAwareSlippage(SlippageConfig(model="flat", min_bps=7.0, max_bps=7.0))
    assert flat.slippage_bps(1, 1_000_000) == pytest.approx(7.0)
    assert flat.slippage_bps(999, 1000) == pytest.approx(7.0)


def test_zero_band_does_not_move_price() -> None:
    zero = DepthAwareSlippage(SlippageConfig(model="flat", min_bps=0.0, max_bps=0.0))
    assert zero.adjusted_fill_price(Side.BUY, 123.45, 10, 1000) == pytest.approx(123.45)
