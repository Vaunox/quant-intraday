"""Tests for corporate-action adjustment (P1.5) — the headline: a split is adjusted right."""

from datetime import date

import pandas as pd
import pytest

from quant.data.hygiene.corporate_actions import (
    CorporateAction,
    CorporateActionAdjuster,
    CorporateActionType,
)
from quant.data.hygiene.errors import CorporateActionError
from quant.data.store.errors import SchemaError
from tests.unit.hygiene_fakes import at, bar, frame

D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
D3 = date(2024, 6, 5)  # ex-date in the split/dividend tests


def _three_days() -> pd.DataFrame:
    """RELIANCE ~2000 for two days, then ~1005 post-1:2-split on D3."""
    return frame(
        [
            bar("RELIANCE", at(D1), o=2000, h=2010, lo=1990, c=2000, v=100),
            bar("RELIANCE", at(D2), o=2005, h=2020, lo=1995, c=2010, v=200),
            bar("RELIANCE", at(D3), o=1005, h=1010, lo=1000, c=1005, v=400),  # post-split
        ]
    )


def test_split_back_adjusts_pre_ex_prices_and_volumes() -> None:
    action = CorporateAction("RELIANCE", D3, CorporateActionType.SPLIT, ratio=2.0)
    adjusted = CorporateActionAdjuster([action]).adjust("RELIANCE", _three_days())

    closes = adjusted["close"].tolist()
    volumes = adjusted["volume"].tolist()
    assert closes == [1000.0, 1005.0, 1005.0]  # pre-ex halved, ex-day unchanged
    assert volumes == [200, 400, 400]  # pre-ex volume doubled (traded value preserved)
    # OHLC all scaled by the same 0.5 factor pre-ex.
    assert adjusted["high"].tolist() == [1005.0, 1010.0, 1010.0]


def test_no_actions_is_identity() -> None:
    raw = _three_days()
    adjusted = CorporateActionAdjuster([]).adjust("RELIANCE", raw)
    pd.testing.assert_frame_equal(adjusted, raw)


def test_action_for_other_symbol_is_ignored() -> None:
    action = CorporateAction("INFY", D3, CorporateActionType.SPLIT, ratio=2.0)
    raw = _three_days()
    adjusted = CorporateActionAdjuster([action]).adjust("RELIANCE", raw)
    pd.testing.assert_frame_equal(adjusted, raw)


def test_dividend_adjusts_by_reference_close() -> None:
    # Dividend 10 on D3; reference close = raw close on D2 (2010) -> factor (2010-10)/2010.
    action = CorporateAction("RELIANCE", D3, CorporateActionType.DIVIDEND, amount=10.0)
    adjusted = CorporateActionAdjuster([action]).adjust("RELIANCE", _three_days())

    factor = (2010.0 - 10.0) / 2010.0
    assert adjusted["close"].iloc[0] == pytest.approx(2000.0 * factor)
    assert adjusted["close"].iloc[2] == 1005.0  # ex-day unchanged
    assert adjusted["volume"].tolist() == [100, 200, 400]  # dividends don't scale volume


def test_compounding_actions_multiply() -> None:
    # A 1:2 split on D2 and another 1:2 split on D3: D1 gets 0.25, D2 gets 0.5, D3 raw.
    actions = [
        CorporateAction("RELIANCE", D2, CorporateActionType.SPLIT, ratio=2.0),
        CorporateAction("RELIANCE", D3, CorporateActionType.SPLIT, ratio=2.0),
    ]
    adjusted = CorporateActionAdjuster(actions).adjust("RELIANCE", _three_days())
    assert adjusted["close"].tolist() == [500.0, 1005.0, 1005.0]
    assert adjusted["volume"].tolist() == [400, 400, 400]


def test_action_before_all_history_is_skipped() -> None:
    action = CorporateAction("RELIANCE", D1, CorporateActionType.SPLIT, ratio=2.0)
    raw = _three_days()
    # No bar strictly before D1 -> nothing to adjust.
    pd.testing.assert_frame_equal(CorporateActionAdjuster([action]).adjust("RELIANCE", raw), raw)


def test_dividend_not_below_reference_raises() -> None:
    action = CorporateAction("RELIANCE", D3, CorporateActionType.DIVIDEND, amount=5000.0)
    with pytest.raises(CorporateActionError, match="not below the reference"):
        CorporateActionAdjuster([action]).adjust("RELIANCE", _three_days())


def test_invalid_ratio_rejected_at_construction() -> None:
    with pytest.raises(CorporateActionError, match="positive ratio"):
        CorporateAction("RELIANCE", D3, CorporateActionType.SPLIT, ratio=0.0)


def test_invalid_dividend_amount_rejected_at_construction() -> None:
    with pytest.raises(CorporateActionError, match="positive amount"):
        CorporateAction("RELIANCE", D3, CorporateActionType.DIVIDEND, amount=0.0)


def test_adjust_does_not_mutate_raw() -> None:
    raw = _three_days()
    before = raw.copy(deep=True)
    CorporateActionAdjuster(
        [CorporateAction("RELIANCE", D3, CorporateActionType.SPLIT, ratio=2.0)]
    ).adjust("RELIANCE", raw)
    pd.testing.assert_frame_equal(raw, before)


def test_deterministic() -> None:
    adjuster = CorporateActionAdjuster(
        [CorporateAction("RELIANCE", D3, CorporateActionType.SPLIT, ratio=2.0)]
    )
    first = adjuster.adjust("RELIANCE", _three_days())
    second = adjuster.adjust("RELIANCE", _three_days())
    pd.testing.assert_frame_equal(first, second)


def test_empty_frame_returns_empty() -> None:
    empty = frame([])
    result = CorporateActionAdjuster([]).adjust("RELIANCE", empty)
    assert result.empty


def test_bad_schema_rejected() -> None:
    with pytest.raises(SchemaError):
        CorporateActionAdjuster([]).adjust("RELIANCE", _three_days().drop(columns=["volume"]))
