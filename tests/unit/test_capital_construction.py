"""Tests for the Capital Layer — portfolio construction + sizing (P3X.7)."""

import numpy as np
import pandas as pd
import pytest

from quant.capital.errors import CapitalError
from quant.capital.portfolio.construction import (
    apply_caps,
    construct_book,
    hrp_weights,
    inverse_vol_weights,
    select_top_quantile,
)
from quant.capital.sizing.sizing import vol_target_scalar

_SECTORS = {f"S{i}": ("Fin" if i < 5 else "Tech") for i in range(10)}


def test_select_top_quantile() -> None:
    scores = pd.Series({f"S{i}": float(i) for i in range(10)})  # S9 highest
    top = select_top_quantile(scores, quantile=0.2)  # top 2 of 10
    assert set(top) == {"S9", "S8"}


def test_inverse_vol_weights_favor_low_vol_and_sum_to_one() -> None:
    vols = pd.Series({"A": 0.10, "B": 0.20})
    w = inverse_vol_weights(vols)
    assert w.sum() == pytest.approx(1.0)
    assert w["A"] == pytest.approx(2.0 / 3.0)  # 1/0.1 : 1/0.2 = 2 : 1
    assert w["A"] > w["B"]


def test_apply_caps_respects_name_and_sector_caps() -> None:
    # All 10 names in Fin/Tech; one name dominates.
    weights = pd.Series({f"S{i}": 0.1 for i in range(10)})
    weights["S0"] = 0.5  # over the 0.05 name cap
    capped = apply_caps(weights, _SECTORS, sector_cap=0.25, name_cap=0.05)
    assert capped.max() <= 0.05 + 1e-12  # name cap
    fin = sum(capped[s] for s in _SECTORS if _SECTORS[s] == "Fin")
    tech = sum(capped[s] for s in _SECTORS if _SECTORS[s] == "Tech")
    assert fin <= 0.25 + 1e-12 and tech <= 0.25 + 1e-12  # sector caps
    assert capped.sum() <= 1.0 + 1e-12  # residual cash allowed when caps bind


def test_hrp_weights_sum_to_one_and_are_long_only() -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(size=(200, 4))
    cov = pd.DataFrame(np.cov(data, rowvar=False), index=list("ABCD"), columns=list("ABCD"))
    w = hrp_weights(cov)
    assert w.sum() == pytest.approx(1.0)
    assert (w >= 0).all()


def test_hrp_runs_on_singular_covariance() -> None:
    # Two identical assets → singular covariance; HRP must not error (it never inverts).
    base = np.random.default_rng(1).normal(size=(150, 1))
    data = np.hstack([base, base, np.random.default_rng(2).normal(size=(150, 2))])
    cov = pd.DataFrame(np.cov(data, rowvar=False), index=list("ABCD"), columns=list("ABCD"))
    w = hrp_weights(cov)
    assert w.sum() == pytest.approx(1.0)
    assert np.isfinite(w.to_numpy()).all()


def test_construct_book_inverse_vol_end_to_end() -> None:
    scores = pd.Series({f"S{i}": float(i) for i in range(10)})
    vols = pd.Series({f"S{i}": 0.1 + 0.01 * i for i in range(10)})
    book = construct_book(
        scores, _SECTORS, quantile=0.4, sector_cap=0.25, name_cap=0.05, volatility=vols
    )
    assert (book.index == scores.index).all()  # full-universe aligned
    assert book.max() <= 0.05 + 1e-12
    assert (book[["S0", "S1"]] == 0.0).all()  # bottom names not selected


def test_vol_target_scalar_caps_at_max_leverage() -> None:
    # Low realised vol would imply scaling up, but it is capped at max_leverage.
    assert vol_target_scalar(0.05, target_vol=0.15, max_leverage=1.0, kelly_fraction=1.0) == 1.0
    # High realised vol scales down (quarter-Kelly).
    s = vol_target_scalar(0.60, target_vol=0.15, max_leverage=1.0, kelly_fraction=0.25)
    assert s == pytest.approx(0.25 * 0.15 / 0.60)


def test_invalid_inputs_raise() -> None:
    with pytest.raises(CapitalError):
        select_top_quantile(pd.Series({"A": 1.0}), quantile=0.0)
    with pytest.raises(CapitalError):
        vol_target_scalar(0.2, target_vol=0.0)
    with pytest.raises(CapitalError):
        construct_book(
            pd.Series({"A": 1.0}), {"A": "Fin"}, method="bogus", volatility=pd.Series({"A": 0.1})
        )
