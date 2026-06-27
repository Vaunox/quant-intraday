"""Tests for benchmark-relative (active) validation (P3X.5) on synthetic series."""

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.validation.active import (
    active_information_ratio,
    active_returns,
    evaluate_active_under_cpcv,
)
from quant.research.validation.cpcv import CombinatorialPurgedCV

_LT = pd.Series(
    pd.date_range("2020-01-31", periods=24, freq="30D", tz=IST) + pd.Timedelta(days=21),
    index=pd.date_range("2020-01-31", periods=24, freq="30D", tz=IST),
    name="t1",
)


def _positive_backtest(train: npt.NDArray[np.intp], test: npt.NDArray[np.intp]) -> pd.Series:
    """A test fold with a positive-mean, varying active return (finite, positive IR)."""
    values = 0.02 + 0.01 * np.cos(test.astype("float64"))
    return pd.Series(values, index=_LT.index[test])


def test_active_returns_subtracts_benchmark() -> None:
    idx = pd.date_range("2020-01-31", periods=3, freq="30D", tz=IST)
    book = pd.Series([0.05, 0.03, 0.04], index=idx)
    benchmark = pd.Series([0.04, 0.04, 0.02], index=idx)
    assert active_returns(book, benchmark).tolist() == pytest.approx([0.01, -0.01, 0.02])


def test_active_ir_sign_and_scale_invariance() -> None:
    a = pd.Series([0.01, 0.03, -0.01, 0.02, 0.0, 0.015, 0.005, 0.02])
    ir = active_information_ratio(a, periods_per_year=12)
    assert ir > 0
    # Sharpe/IR is scale-invariant: doubling every active return leaves the IR unchanged.
    assert active_information_ratio(a * 2.0, periods_per_year=12) == pytest.approx(ir)
    # A zero-mean series has ~zero IR.
    zero = pd.Series([0.01, -0.01, 0.01, -0.01])
    assert active_information_ratio(zero, periods_per_year=12) == pytest.approx(0.0)


def test_evaluate_active_under_cpcv_positive_edge() -> None:
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)  # phi = C(3,1) = 3 paths
    ev = evaluate_active_under_cpcv(_LT, _positive_backtest, cpcv)
    assert ev.distribution.num_paths == 3
    assert ev.annualised_ir > 0.0  # positive-mean active → positive IR
    assert ev.fraction_negative == pytest.approx(0.0)  # every path positive
    dsr = ev.deflated_sharpe(n_trials=5)
    assert 0.0 <= dsr <= 1.0
    assert ev.dedup_tstat > 0.0


def test_dedup_tstat_is_smaller_than_path_concatenated() -> None:
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_active_under_cpcv(_LT, _positive_backtest, cpcv)
    values = ev.combined.to_numpy(dtype="float64")
    concat_t = values.mean() / values.std(ddof=1) * np.sqrt(values.size)
    # de-dup divides the path-concatenated t by sqrt(phi) (phi = 3 here) — strictly smaller.
    assert ev.dedup_tstat == pytest.approx(concat_t / np.sqrt(3))
    assert ev.dedup_tstat < concat_t
