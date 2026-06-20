"""Reusable structural leakage / train-serve-skew assertions (P1.8).

These are the anti-leakage guarantees the adversarial suite enforces (Deep Dive #1 §2.4;
Part I Rule 2). Each is a single assertion that **raises ``AssertionError`` on a leaky
input**, so the same helper both (a) guards the real feature library in CI and (b) is
shown — via ``pytest.raises`` — to fire on a deliberately-leaky feature.

Imported by the ``tests/adversarial/test_*`` modules; not collected itself.
"""

from collections.abc import Callable
from datetime import datetime

import pandas as pd

#: A feature is any pure transform from an input frame to a Series or frame of values.
FeatureFn = Callable[[pd.DataFrame], "pd.Series | pd.DataFrame"]
#: The incremental (live) path: features for the single bar at ``asof``.
AsofFn = Callable[[pd.DataFrame, datetime], pd.Series]
#: The vectorized (backtest) path: features for every row, indexed by timestamp.
FrameFn = Callable[[pd.DataFrame], pd.DataFrame]

_RTOL = 1e-12
_ATOL = 1e-12


def assert_no_lookahead(feature: FeatureFn, data: pd.DataFrame, *, split: int) -> None:
    """Assert ``feature`` is causal (no forward-shift leakage).

    Computing the feature on the first ``split`` rows must equal the first ``split`` rows
    of the full computation — i.e. appending future rows never changes a past value. A
    feature that peeks forward (``shift(-1)``, a centred window, …) changes retroactively
    and raises :class:`AssertionError`.
    """
    full = feature(data)
    prefix = feature(data.iloc[:split])
    _assert_prefix_equal(full, prefix, split)


def assert_skew_free(frame_fn: FrameFn, asof_fn: AsofFn, bars: pd.DataFrame) -> None:
    """Assert the vectorized and incremental paths agree for every bar (no train/serve skew).

    For each timestamp, the incremental (live) feature vector must equal that row of the
    vectorized (backtest) frame. Any divergence — the classic train/serve skew — raises.
    """
    vectorized = frame_fn(bars)
    for timestamp in bars["timestamp"]:
        incremental = asof_fn(bars, timestamp)
        pd.testing.assert_series_equal(
            incremental,
            vectorized.loc[timestamp],
            check_names=False,
            rtol=_RTOL,
            atol=_ATOL,
        )


def assert_trailing_only(transform: Callable[[pd.Series], pd.Series], series: pd.Series) -> None:
    """Assert a normalizer uses only trailing data.

    Perturbing the *last* value must leave every *earlier* output unchanged: a trailing
    window only reaches backward, so a late change cannot touch the past. A full-sample
    statistic (mean/std over everything) shifts every row and raises.
    """
    last = len(series) - 1
    baseline = transform(series)
    perturbed = series.copy()
    perturbed.iloc[last] = float(perturbed.iloc[last]) + 1_000_000.0
    after = transform(perturbed)
    pd.testing.assert_series_equal(
        baseline.iloc[:last], after.iloc[:last], check_names=False, rtol=_RTOL, atol=_ATOL
    )


def max_abs_future_correlation(feature: pd.Series, future_label: pd.Series) -> float:
    """Return ``|corr(feature, future_label)|`` over the rows where both are defined."""
    aligned = pd.concat([feature.rename("f"), future_label.rename("y")], axis=1).dropna()
    if len(aligned) < 3:
        return 0.0
    correlation = aligned["f"].corr(aligned["y"])
    return 0.0 if pd.isna(correlation) else abs(float(correlation))


def assert_no_future_correlation(
    feature: pd.Series, future_label: pd.Series, *, max_abs_corr: float
) -> None:
    """Assert ``feature`` is not correlated with a *future* label beyond plausibility.

    A legitimate feature (computed from data at or before the bar) cannot be near-perfectly
    correlated with a forward return; one that mechanically contains the future is, and
    raises. The threshold is deliberately high — this flags egregious leakage, not edge.
    """
    correlation = max_abs_future_correlation(feature, future_label)
    assert correlation < max_abs_corr, (
        f"feature correlates {correlation:.4f} with the future label "
        f"(>= {max_abs_corr}); this looks like lookahead leakage"
    )


def _assert_prefix_equal(
    full: "pd.Series | pd.DataFrame", prefix: "pd.Series | pd.DataFrame", split: int
) -> None:
    """Assert the first ``split`` rows of ``full`` equal ``prefix`` (positionally)."""
    if isinstance(full, pd.DataFrame):
        assert isinstance(prefix, pd.DataFrame)
        pd.testing.assert_frame_equal(
            full.iloc[:split].reset_index(drop=True),
            prefix.reset_index(drop=True),
            check_exact=False,
            rtol=_RTOL,
            atol=_ATOL,
        )
    else:
        assert isinstance(prefix, pd.Series)
        pd.testing.assert_series_equal(
            full.iloc[:split].reset_index(drop=True),
            prefix.reset_index(drop=True),
            check_names=False,
            check_exact=False,
            rtol=_RTOL,
            atol=_ATOL,
        )
