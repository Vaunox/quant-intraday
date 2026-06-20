"""Trailing-only normalization: a late value must never change an earlier normalized value.

Enforces that the normalizers use only trailing data (Deep Dive #1 §2.4(c); §2.3) and
proves the check catches a full-sample normalizer.
"""

from collections.abc import Callable

import pandas as pd
import pytest

from quant.data.features import robust_zscore, rolling_zscore, winsorize
from tests.adversarial import leakage, leaky_features, sample_data

pytestmark = pytest.mark.adversarial

_SERIES = pd.Series(sample_data.make_bars(60)["close"].to_numpy(), name="x")

_NORMALIZERS: dict[str, Callable[[pd.Series], pd.Series]] = {
    "rolling_zscore": lambda s: rolling_zscore(s, 10),
    "robust_zscore": lambda s: robust_zscore(s, 10),
    "winsorize": lambda s: winsorize(s, window=10, lower_pct=5.0, upper_pct=95.0),
}


@pytest.mark.parametrize("transform", list(_NORMALIZERS.values()), ids=list(_NORMALIZERS))
def test_normalizers_are_trailing_only(transform: Callable[[pd.Series], pd.Series]) -> None:
    leakage.assert_trailing_only(transform, _SERIES)


def test_tripwire_full_sample_zscore_is_caught() -> None:
    with pytest.raises(AssertionError):
        leakage.assert_trailing_only(leaky_features.full_sample_zscore, _SERIES)
