"""Tests for the Indian MIS transaction-cost model (P2.1, Deep Dive #2 §4b.6).

Each component is hand-computed against the configured rate schedule, and the per-order
brokerage cap is exercised on both sides of the ``min``.
"""

import pytest

from quant.core.config import CostConfig, load_config
from quant.core.types import Side
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.errors import CostModelError

CFG = load_config(environ={}).costs
MODEL = IndianCostModel(CFG)


def test_buy_breakdown_matches_schedule() -> None:
    # turnover = 100 * 10 = 1000.
    cost = MODEL.cost_for_fill(Side.BUY, 100.0, 10)
    assert cost.brokerage == pytest.approx(0.0003 * 1000)  # 0.3 (below the Rs.20 cap)
    assert cost.stt == 0.0  # no STT on the buy leg
    assert cost.exchange_txn == pytest.approx(0.00003 * 1000)  # 0.03
    assert cost.sebi_charges == pytest.approx(0.000001 * 1000)  # 0.001
    assert cost.stamp_duty == pytest.approx(0.00003 * 1000)  # 0.03 (buy side)
    assert cost.gst == pytest.approx(0.18 * (0.3 + 0.03 + 0.001))  # GST base incl. SEBI
    assert cost.total == pytest.approx(0.3 + 0.03 + 0.001 + 0.03 + 0.18 * 0.331)


def test_sell_breakdown_has_stt_and_no_stamp() -> None:
    cost = MODEL.cost_for_fill(Side.SELL, 100.0, 10)
    assert cost.stt == pytest.approx(0.00025 * 1000)  # 0.25, sell side only
    assert cost.stamp_duty == 0.0  # no stamp duty on the sell leg
    # GST base excludes the one-sided taxes (STT/stamp), only brokerage+exchange+SEBI.
    assert cost.gst == pytest.approx(0.18 * (0.3 + 0.03 + 0.001))


def test_brokerage_cap_binds_for_large_turnover() -> None:
    # turnover = 1000 * 1000 = 1_000_000; 0.03% = 300 > Rs.20 cap -> capped at 20.
    cost = MODEL.cost_for_fill(Side.BUY, 1000.0, 1000)
    assert cost.brokerage == pytest.approx(CFG.brokerage_cap_inr)  # 20.0


def test_brokerage_percentage_binds_for_small_turnover() -> None:
    # turnover = 10 * 1 = 10; 0.03% = 0.003 < Rs.20 -> percentage applies.
    cost = MODEL.cost_for_fill(Side.BUY, 10.0, 1)
    assert cost.brokerage == pytest.approx(0.0003 * 10)


def test_total_sums_components() -> None:
    cost = MODEL.cost_for_fill(Side.SELL, 250.0, 7)
    assert cost.total == pytest.approx(
        cost.brokerage
        + cost.stt
        + cost.exchange_txn
        + cost.sebi_charges
        + cost.stamp_duty
        + cost.gst
    )


def test_round_trip_within_liquid_name_band() -> None:
    # A liquid round trip (buy + sell) should land in the documented ~0.12-0.20% band
    # for a mid-sized position where the Rs.20 cap does not dominate.
    price, qty = 500.0, 200  # turnover 100_000 per leg
    buy = MODEL.cost_for_fill(Side.BUY, price, qty)
    sell = MODEL.cost_for_fill(Side.SELL, price, qty)
    round_trip_pct = (buy.total + sell.total) / (price * qty) * 100
    assert 0.04 <= round_trip_pct <= 0.20


def test_zero_rates_give_zero_cost() -> None:
    zero = IndianCostModel(
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
    assert zero.cost_for_fill(Side.BUY, 100.0, 10).total == 0.0


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_non_positive_price_rejected(price: float) -> None:
    with pytest.raises(CostModelError, match="price"):
        MODEL.cost_for_fill(Side.BUY, price, 10)


@pytest.mark.parametrize("quantity", [0, -5])
def test_non_positive_quantity_rejected(quantity: int) -> None:
    with pytest.raises(CostModelError, match="quantity"):
        MODEL.cost_for_fill(Side.BUY, 100.0, quantity)
