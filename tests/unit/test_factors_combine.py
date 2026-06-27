"""Tests for signal combination (P3X.4) on synthetic factor panels."""

import math

import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.factors import (
    EqualWeightComposite,
    FactorError,
    WeightedComposite,
    sector_neutral_composite,
)

_SECTORS = {"A": "S1", "B": "S1", "C": "S2", "D": "S2"}
_IDX = pd.DatetimeIndex([pd.Timestamp("2020-01-31", tz=IST), pd.Timestamp("2020-02-28", tz=IST)])
_Z = 1.0 / math.sqrt(2.0)  # sector-neutral z of the smaller of two values is -1/√2, larger +1/√2


def _factor(values: dict[str, float]) -> pd.DataFrame:
    """A constant (across the two dates) factor panel from per-symbol values."""
    return pd.DataFrame({s: [v, v] for s, v in values.items()}, index=_IDX)


def test_equal_weight_composite_is_sector_neutral_mean() -> None:
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})  # z: A,C=-Z ; B,D=+Z
    f2 = _factor({"A": 5.0, "B": 1.0, "C": 2.0, "D": 8.0})  # z: A,D=+Z, B,C=-Z
    comp = sector_neutral_composite({"f1": f1, "f2": f2}, _SECTORS)
    # A = mean(-Z, +Z) = 0 ; D = mean(+Z, +Z) = +Z ; C = mean(-Z, -Z) = -Z.
    assert comp.loc[_IDX[0], "A"] == pytest.approx(0.0)
    assert comp.loc[_IDX[0], "D"] == pytest.approx(_Z)
    assert comp.loc[_IDX[0], "C"] == pytest.approx(-_Z)


def test_sector_neutral_removes_sector_level() -> None:
    # C has a high RAW value (10) but is the low name within its own sector → it scores negative.
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})
    comp = sector_neutral_composite({"f1": f1}, _SECTORS)
    assert comp.loc[_IDX[0], "C"] == pytest.approx(-_Z)
    assert comp.loc[_IDX[0], "B"] == pytest.approx(+_Z)


def test_weighted_composite_weights_factors() -> None:
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})  # zA=-Z
    f2 = _factor({"A": 5.0, "B": 1.0, "C": 2.0, "D": 8.0})  # zA=+Z
    comp = WeightedComposite(_SECTORS, {"f1": 1.0, "f2": 3.0}).combine({"f1": f1, "f2": f2})
    # A = (1*(-Z) + 3*(+Z)) / 4 = +Z/2.
    assert comp.loc[_IDX[0], "A"] == pytest.approx(_Z / 2.0)


def test_nan_factor_cell_is_skipped_not_zeroed() -> None:
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})
    f2 = _factor({"A": 5.0, "B": 1.0, "C": 2.0, "D": 8.0})
    f2.loc[_IDX[0], "A"] = float("nan")
    comp = sector_neutral_composite({"f1": f1, "f2": f2}, _SECTORS)
    # With f2[A] missing at date 0, A's composite is just f1's z (=-Z), not averaged toward 0.
    assert comp.loc[_IDX[0], "A"] == pytest.approx(-_Z)


def test_equal_weight_combiner_matches_function() -> None:
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})
    combiner = EqualWeightComposite(_SECTORS)
    direct = sector_neutral_composite({"f1": f1}, _SECTORS)
    pd.testing.assert_frame_equal(combiner.combine({"f1": f1}), direct)


def test_invalid_inputs_raise() -> None:
    f1 = _factor({"A": 1.0, "B": 3.0, "C": 10.0, "D": 20.0})
    with pytest.raises(FactorError):
        sector_neutral_composite({}, _SECTORS)
    with pytest.raises(FactorError):
        sector_neutral_composite({"f1": f1}, _SECTORS, weights={"other": 1.0})
