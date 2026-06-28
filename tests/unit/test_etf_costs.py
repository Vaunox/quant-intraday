"""Unit tests for the Step 2 ETF cost model."""

from __future__ import annotations

import pytest

from quant.research.etf.costs import (
    ChargeSchedule,
    ETFCostModel,
    LegProfile,
    default_cost_model,
)


def _model(spread_bps: float = 10.0, stt_sell_bps: float = 0.1) -> ETFCostModel:
    """A one-leg model with round charge numbers for arithmetic checks."""
    legs = {
        "X": LegProfile(
            "X", spread_bps=spread_bps, expense_ratio_annual=0.01, stt_sell_bps=stt_sell_bps
        )
    }
    return ETFCostModel(legs=legs)


def test_buy_side_has_stamp_no_stt_no_dp() -> None:
    cost = _model().trade_cost("X", 100_000.0, side="buy")
    assert cost.stamp == pytest.approx(100_000 * 0.00015)  # 0.015% buy
    assert cost.stt == 0.0
    assert cost.dp == 0.0
    assert cost.spread == pytest.approx(100_000 * (10.0 / 2) / 1e4)  # half spread on buy


def test_sell_side_has_stt_and_dp_no_stamp() -> None:
    cost = _model().trade_cost("X", 100_000.0, side="sell")
    assert cost.stamp == 0.0
    assert cost.stt == pytest.approx(100_000 * 0.1 / 1e4)
    assert cost.dp == pytest.approx(15.93)


def test_round_trip_spread_sums_to_full_quoted_spread() -> None:
    # With all statutory charges zeroed, round trip cost == full spread in bps.
    legs = {"X": LegProfile("X", spread_bps=8.0, expense_ratio_annual=0.0, stt_sell_bps=0.0)}
    bare = ChargeSchedule(
        brokerage_per_order=0.0,
        exchange_txn_rate=0.0,
        sebi_rate=0.0,
        stamp_buy_rate=0.0,
        gst_rate=0.0,
        dp_charge_per_sell=0.0,
    )
    model = ETFCostModel(legs=legs, charges=bare)
    assert model.round_trip_bps("X", 50_000.0) == pytest.approx(8.0)


def test_flat_dp_charge_dominates_at_small_trade_value() -> None:
    # The regressive flat DP fee: ~10 bps on a small leg, ~1 bps on a large one.
    model = _model(spread_bps=3.0)
    small = model.round_trip_bps("X", 16_000.0)
    large = model.round_trip_bps("X", 1_600_000.0)
    assert small > large
    dp_bps_small = 15.93 / 16_000 * 1e4
    assert dp_bps_small > 9.0  # the DP charge alone is the dominant cost at Rs 1 lakh scale
    assert small > 12.0  # spread (3) + stamp (1.5) + DP (~10) + bits


def test_round_trip_requires_positive_value() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _model().round_trip_bps("X", 0.0)


def test_holding_cost_scales_with_ter_and_time() -> None:
    model = _model()  # TER 1%/yr
    assert model.holding_cost_bps("X", 365.0) == pytest.approx(100.0)  # 1% = 100 bps/yr
    assert model.holding_cost_bps("X", 36.5) == pytest.approx(10.0)


def test_default_model_covers_frozen_universe_with_resolved_stt() -> None:
    model = default_cost_model()
    assert set(model.legs) == {
        "NIFTYBEES",
        "BANKBEES",
        "MON100",
        "GOLDBEES",
        "SILVERBEES",
        "LIQUIDBEES",
    }
    assert model.legs["NIFTYBEES"].stt_sell_bps == 0.1  # equity ETF
    assert model.legs["GOLDBEES"].stt_sell_bps == 0.0  # commodity, no STT
    assert model.legs["MON100"].stt_sell_bps == 0.0  # international, exempt
