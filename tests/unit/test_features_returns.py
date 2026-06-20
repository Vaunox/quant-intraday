"""Tests for return-transform features (P1.6)."""

import math
from datetime import date

import pandas as pd
import pytest

from quant.data.features.returns import log_return
from tests.unit.hygiene_fakes import at, frame, good

D1 = date(2024, 6, 3)


def _closes(closes: list[float]) -> pd.DataFrame:
    return frame([good("X", at(D1, 9, 15 + i), c) for i, c in enumerate(closes)])


def test_log_return_values() -> None:
    result = log_return(_closes([100, 110, 121]), 1)
    assert result.name == "ret_1"
    assert pd.isna(result.iloc[0])  # first bar: no prior close
    assert result.iloc[1] == pytest.approx(math.log(110 / 100))
    assert result.iloc[2] == pytest.approx(math.log(121 / 110))


def test_log_return_horizon_has_nan_prefix() -> None:
    result = log_return(_closes([100, 110, 121, 133, 145]), 3)
    assert result.iloc[:3].isna().all()  # need 3 prior bars
    assert result.iloc[3] == pytest.approx(math.log(133 / 100))
    assert result.name == "ret_3"


def test_log_return_is_causal_under_append() -> None:
    # Appending a future bar must not change earlier return values (point-in-time).
    short = log_return(_closes([100, 110, 121]), 1)
    long = log_return(_closes([100, 110, 121, 99, 150]), 1)
    pd.testing.assert_series_equal(long.iloc[:3], short, check_exact=False)


def test_log_return_rejects_non_positive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        log_return(_closes([100, 101]), 0)
