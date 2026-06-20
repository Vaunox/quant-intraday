"""Tests for the liquidity screen + ESM/T2T exclusion (P1.5)."""

from datetime import date

from quant.core.config import UniverseEligibility
from quant.data.hygiene.liquidity import (
    REASON_ADV_BELOW_MIN,
    REASON_ESM_T2T_EXCLUDED,
    REASON_SPREAD_TOO_WIDE,
    LiquidityMetrics,
    LiquidityScreen,
    average_daily_value,
)
from tests.unit.hygiene_fakes import at, bar, frame

DAY1 = date(2024, 6, 3)
DAY2 = date(2024, 6, 4)

ELIGIBILITY = UniverseEligibility(min_adv_inr=5e8, max_spread_bps=5.0, exclude_esm_t2t=True)
LIQUID = LiquidityMetrics("LIQUID", adv_inr=1e9, median_spread_bps=3.0)
THIN = LiquidityMetrics("THIN", adv_inr=1e8, median_spread_bps=3.0)
WIDE = LiquidityMetrics("WIDE", adv_inr=1e9, median_spread_bps=10.0)
ESM = LiquidityMetrics("ESMNAME", adv_inr=1e9, median_spread_bps=3.0)


def test_eligible_and_rejected_split() -> None:
    result = LiquidityScreen(ELIGIBILITY).screen([LIQUID, THIN, WIDE, ESM], esm_t2t={"ESMNAME"})
    assert result.eligible == ("LIQUID",)
    rejected = {r.symbol: r.reasons for r in result.rejected}
    assert rejected["THIN"] == (REASON_ADV_BELOW_MIN,)
    assert rejected["WIDE"] == (REASON_SPREAD_TOO_WIDE,)
    assert rejected["ESMNAME"] == (REASON_ESM_T2T_EXCLUDED,)


def test_multiple_reasons_accumulate() -> None:
    bad = LiquidityMetrics("BAD", adv_inr=1e6, median_spread_bps=50.0)
    reasons = LiquidityScreen(ELIGIBILITY).evaluate(bad, is_esm_t2t=True)
    assert set(reasons) == {REASON_ADV_BELOW_MIN, REASON_SPREAD_TOO_WIDE, REASON_ESM_T2T_EXCLUDED}


def test_esm_not_excluded_when_toggle_off() -> None:
    eligibility = UniverseEligibility(min_adv_inr=5e8, max_spread_bps=5.0, exclude_esm_t2t=False)
    result = LiquidityScreen(eligibility).screen([ESM], esm_t2t={"ESMNAME"})
    assert result.eligible == ("ESMNAME",)  # liquid + tight; ESM flag ignored when off


def test_eligible_symbols_are_sorted() -> None:
    a = LiquidityMetrics("AAA", adv_inr=1e9, median_spread_bps=1.0)
    z = LiquidityMetrics("ZZZ", adv_inr=1e9, median_spread_bps=1.0)
    result = LiquidityScreen(ELIGIBILITY).screen([z, a])
    assert result.eligible == ("AAA", "ZZZ")


def test_screen_with_no_esm_set_keeps_liquid_names() -> None:
    result = LiquidityScreen(ELIGIBILITY).screen([LIQUID])
    assert result.eligible == ("LIQUID",)
    assert result.rejected == ()


def test_average_daily_value_means_over_days() -> None:
    bars = frame(
        [
            bar("X", at(DAY1, 9, 15), o=100, h=100, lo=100, c=100, v=10),  # value 1000
            bar("X", at(DAY1, 9, 16), o=100, h=100, lo=100, c=100, v=20),  # value 2000
            bar("X", at(DAY2, 9, 15), o=200, h=200, lo=200, c=200, v=10),  # value 2000
        ]
    )
    # Day1 traded value 3000, Day2 2000 -> ADV = mean = 2500.
    assert average_daily_value(bars) == 2500.0


def test_average_daily_value_empty_is_zero() -> None:
    assert average_daily_value(frame([])) == 0.0
