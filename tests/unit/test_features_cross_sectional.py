"""Tests for cross-sectional sector-neutral features (P1.7)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from quant.data.features.cross_sectional import cross_sectional_rank, sector_neutral_zscore
from tests.unit.hygiene_fakes import IST

T0 = datetime(2024, 6, 3, 9, 15, tzinfo=IST)
T1 = datetime(2024, 6, 3, 9, 16, tzinfo=IST)


def _panel() -> pd.DataFrame:
    return pd.DataFrame({"AAA": [1.0, 4.0], "BBB": [2.0, 5.0], "CCC": [3.0, 6.0]}, index=[T0, T1])


def test_cross_sectional_rank_is_centred() -> None:
    ranks = cross_sectional_rank(_panel())
    # Row [1,2,3] -> pct ranks [1/3, 2/3, 1] minus 0.5.
    assert ranks["AAA"].iloc[0] == pytest.approx(1 / 3 - 0.5)
    assert ranks["BBB"].iloc[0] == pytest.approx(2 / 3 - 0.5)
    assert ranks["CCC"].iloc[0] == pytest.approx(1.0 - 0.5)


def test_cross_sectional_rank_skips_nan() -> None:
    panel = pd.DataFrame({"AAA": [1.0], "BBB": [np.nan], "CCC": [3.0]}, index=[T0])
    ranks = cross_sectional_rank(panel)
    assert bool(ranks["BBB"].isna().iloc[0])  # NaN metric excluded from ranking
    assert ranks["AAA"].iloc[0] == pytest.approx(0.5 - 0.5)  # lowest of the two valid


def test_sector_neutral_zscore_within_sector() -> None:
    panel = pd.DataFrame({"A1": [1.0], "A2": [3.0], "B1": [10.0], "B2": [20.0]}, index=[T0])
    sectors = {"A1": "TECH", "A2": "TECH", "B1": "BANK", "B2": "BANK"}
    result = sector_neutral_zscore(panel, sectors)
    # TECH: mean 2, std sqrt(2) -> (1-2)/sqrt2, (3-2)/sqrt2.
    assert result["A1"].iloc[0] == pytest.approx(-1 / np.sqrt(2))
    assert result["A2"].iloc[0] == pytest.approx(1 / np.sqrt(2))
    # BANK: mean 15, std sqrt(50).
    assert result["B1"].iloc[0] == pytest.approx((10 - 15) / np.sqrt(50))


def test_sector_neutral_single_name_sector_is_nan() -> None:
    panel = pd.DataFrame({"A1": [1.0], "B1": [10.0]}, index=[T0])
    result = sector_neutral_zscore(panel, {"A1": "TECH", "B1": "BANK"})
    assert bool(result["A1"].isna().iloc[0])  # one name -> no dispersion


def test_sector_neutral_missing_mapping_raises() -> None:
    panel = pd.DataFrame({"A1": [1.0], "B1": [2.0]}, index=[T0])
    with pytest.raises(ValueError, match="missing a sector"):
        sector_neutral_zscore(panel, {"A1": "TECH"})
