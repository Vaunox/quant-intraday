"""Tests for split/bonus panel back-adjustment (P3X.1e)."""

import numpy as np
import pandas as pd
import pytest

from quant.research.factors.corporate_actions import back_adjust_for_splits
from quant.research.factors.errors import FactorError


def _panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2020-01-01 15:30", periods=10, freq="B", tz="Asia/Kolkata")
    # X: 1:2 split on index 5 (100 -> 50). Y: a REAL crash on index 5 (100 -> 50), no CA event.
    x = [100.0] * 5 + [50.0] * 5
    y = [100.0] * 5 + [50.0] * 5
    close = pd.DataFrame({"X": x, "Y": y}, index=dates)
    volume = pd.DataFrame({"X": [1000] * 10, "Y": [1000] * 10}, index=dates, dtype="float64")
    return close, volume


def test_split_is_back_adjusted_continuous() -> None:
    close, volume = _panels()
    ex_date = close.index[5]
    adj_close, adj_volume = back_adjust_for_splits(close, volume, [("X", ex_date)])
    # X becomes a continuous ~50 series (pre-split 100s scaled by 0.5); no fake -50% return left.
    assert np.allclose(adj_close["X"].to_numpy(), 50.0)
    assert np.allclose(adj_volume["X"].iloc[:5].to_numpy(), 2000.0)  # volume scaled up inversely
    returns = adj_close["X"].pct_change().dropna()
    assert returns.abs().max() < 1e-9  # the split jump is gone


def test_real_crash_is_preserved() -> None:
    close, volume = _panels()
    # Y has NO corporate action — its genuine -50% crash must survive untouched.
    adj_close, _ = back_adjust_for_splits(close, volume, [("X", close.index[5])])
    assert np.allclose(adj_close["Y"].iloc[:5].to_numpy(), 100.0)
    assert np.allclose(adj_close["Y"].iloc[5:].to_numpy(), 50.0)


def test_misaligned_exdate_is_skipped() -> None:
    close, volume = _panels()
    # Ex-date on a flat day (index 2, no drop) -> observed ratio ~1.0 -> not adjusted (guarded).
    adj_close, _ = back_adjust_for_splits(close, volume, [("X", close.index[2])])
    assert np.allclose(adj_close["X"].iloc[:5].to_numpy(), 100.0)  # unchanged


def test_unknown_symbol_ignored_and_misalignment_raises() -> None:
    close, volume = _panels()
    # An event for a symbol not in the panel is a no-op.
    adj_close, _ = back_adjust_for_splits(close, volume, [("ZZZ", close.index[5])])
    assert np.allclose(adj_close["X"].to_numpy(), close["X"].to_numpy())
    with pytest.raises(FactorError):
        back_adjust_for_splits(close, volume.drop(columns=["Y"]), [])
