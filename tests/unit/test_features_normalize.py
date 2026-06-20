"""Tests for feature normalization & winsorization (P1.7, §2.3)."""

import numpy as np
import pandas as pd
import pytest

from quant.data.features.normalize import robust_zscore, rolling_zscore, winsorize


def test_winsorize_clips_to_trailing_upper_quantile() -> None:
    series = pd.Series([10.0] * 9 + [1000.0], name="x")
    result = winsorize(series, window=10, lower_pct=5.0, upper_pct=95.0)
    expected_upper = series.rolling(10).quantile(0.95).iloc[-1]
    assert result.iloc[-1] == pytest.approx(expected_upper)
    assert result.iloc[-1] < 1000.0  # the spike was capped
    assert result.name == "x"


def test_winsorize_clips_low_outlier_up() -> None:
    series = pd.Series([10.0] * 9 + [0.0])
    result = winsorize(series, window=10, lower_pct=5.0, upper_pct=95.0)
    assert result.iloc[-1] > 0.0  # the low spike was lifted to the lower quantile


def test_winsorize_is_causal() -> None:
    series = pd.Series([1.0, 5, 2, 8, 3, 100, 4, 9], name="x")
    full = winsorize(series, window=4, lower_pct=10.0, upper_pct=90.0)
    prefix = winsorize(series.iloc[:5], window=4, lower_pct=10.0, upper_pct=90.0)
    pd.testing.assert_series_equal(full.iloc[:5], prefix)


def test_rolling_zscore_matches_window_stats() -> None:
    series = pd.Series([1.0, 2, 3, 4, 10])
    result = rolling_zscore(series, 3)
    window = [3.0, 4.0, 10.0]
    expected = (10.0 - np.mean(window)) / np.std(window, ddof=1)
    assert result.iloc[-1] == pytest.approx(expected)
    assert pd.isna(result.iloc[0])


def test_robust_zscore_uses_median_and_iqr() -> None:
    series = pd.Series([1.0, 2, 3, 4, 10])
    result = robust_zscore(series, 3)
    window = np.array([3.0, 4.0, 10.0])
    iqr = np.quantile(window, 0.75) - np.quantile(window, 0.25)
    expected = (10.0 - np.median(window)) / iqr
    assert result.iloc[-1] == pytest.approx(expected)


def test_robust_zscore_flat_window_is_nan() -> None:
    series = pd.Series([5.0, 5, 5, 5])
    assert robust_zscore(series, 3).iloc[-1] != robust_zscore(series, 3).iloc[-1]  # NaN


@pytest.mark.parametrize("func", [rolling_zscore, robust_zscore])
def test_zscore_window_must_exceed_one(func: object) -> None:
    with pytest.raises(ValueError, match="window"):
        func(pd.Series([1.0, 2.0]), 1)  # type: ignore[operator]


def test_winsorize_rejects_bad_percentiles() -> None:
    with pytest.raises(ValueError, match="lower_pct"):
        winsorize(pd.Series([1.0, 2.0, 3.0]), window=2, lower_pct=90.0, upper_pct=10.0)
