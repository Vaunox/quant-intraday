"""Tests for ClusterSelectionCombiner — the honesty guarantees, made executable (P3X.4b).

These mirror the P1.8 adversarial-leakage intent: prove the combiner cannot see the future and is
reproducible, BEFORE trusting any CPCV number it feeds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.research.factors.cluster_selection_combiner import ClusterSelectionCombiner


# --------------------------------------------------------------------------- #
# fixtures: a synthetic monthly cross-section with a clear "ideal" region
# --------------------------------------------------------------------------- #
@pytest.fixture
def panel() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 120
    # three sign-aligned factors; higher = more desirable
    momentum = rng.normal(0, 1, n)
    low_vol = rng.normal(0, 1, n)  # already entered as -volatility upstream
    resid_mom = rng.normal(0, 1, n)
    syms = [f"SYM{i:03d}" for i in range(n)]
    return pd.DataFrame(
        {"momentum": momentum, "low_vol": low_vol, "resid_mom": resid_mom},
        index=pd.Index(syms, name="symbol"),
    )


# --------------------------------------------------------------------------- #
# 1. determinism — identical input -> identical output (reproducible CPCV)
# --------------------------------------------------------------------------- #
def test_deterministic(panel: pd.DataFrame) -> None:
    c = ClusterSelectionCombiner(k=5)
    s1 = c.combine(panel)
    s2 = c.combine(panel)
    pd.testing.assert_series_equal(s1, s2)


# --------------------------------------------------------------------------- #
# 2. purity / no cross-call state — order of dates cannot change a date's score
#    (the structural no-look-ahead guarantee: combine() sees only THIS date)
# --------------------------------------------------------------------------- #
def test_pure_no_hidden_state(panel: pd.DataFrame) -> None:
    c = ClusterSelectionCombiner(k=5)
    baseline = c.combine(panel)

    # interleave unrelated cross-sections; the target date's output must not move
    other = panel.sample(frac=1.0, random_state=99) * 3.0 + 1.0
    _ = c.combine(other)
    again = c.combine(panel)
    pd.testing.assert_series_equal(baseline, again)


# --------------------------------------------------------------------------- #
# 3. no-future-leak — perturbing FUTURE rows must not change CURRENT scores.
#    Since combine() is per-date, we assert it ignores anything not in `panel`.
# --------------------------------------------------------------------------- #
def test_future_rows_do_not_leak(panel: pd.DataFrame) -> None:
    c = ClusterSelectionCombiner(k=5)
    now = c.combine(panel)

    # a "future month" with wildly different distribution
    future = panel.copy()
    future.iloc[:] = np.random.default_rng(123).normal(50, 10, future.shape)
    # scoring the future date does not retroactively alter the present one
    _ = c.combine(future)
    now_again = c.combine(panel)
    pd.testing.assert_series_equal(now, now_again)


# --------------------------------------------------------------------------- #
# 4. ex-ante selection is thesis-driven — the top-scored names lean toward the
#    pre-specified direction w, NOT toward any (absent) forward return.
# --------------------------------------------------------------------------- #
def test_top_names_align_with_thesis(panel: pd.DataFrame) -> None:
    w = {"momentum": 1.0, "low_vol": 1.0, "resid_mom": 1.0}
    c = ClusterSelectionCombiner(k=5, thesis_weights=w)
    scores = c.combine(panel).dropna()

    top = scores.nlargest(20).index
    bottom = scores.nsmallest(20).index
    thesis = panel[["momentum", "low_vol", "resid_mom"]].sum(axis=1)
    # top-scored names sit higher on the thesis composite than bottom-scored
    assert thesis.loc[top].mean() > thesis.loc[bottom].mean()


# --------------------------------------------------------------------------- #
# 5. NaN names are never fabricated — missing factor -> NaN score, not a guess
# --------------------------------------------------------------------------- #
def test_missing_factor_yields_nan(panel: pd.DataFrame) -> None:
    p = panel.copy()
    p.loc["SYM000", "momentum"] = np.nan
    c = ClusterSelectionCombiner(k=5)
    scores = c.combine(p)
    assert np.isnan(scores.loc["SYM000"])
    assert scores.dropna().shape[0] == p.shape[0] - 1


# --------------------------------------------------------------------------- #
# 6. thin cross-section falls back to thesis projection (no degenerate K-Means)
# --------------------------------------------------------------------------- #
def test_thin_cross_section_fallback(panel: pd.DataFrame) -> None:
    thin = panel.iloc[:8]  # fewer than k * min_names_per_cluster_factor
    c = ClusterSelectionCombiner(k=5)
    scores = c.combine(thin)
    assert scores.dropna().shape[0] == 8  # still scores everyone, no crash


# --------------------------------------------------------------------------- #
# 7. unknown thesis factor is rejected loudly (config error, not silent drift)
# --------------------------------------------------------------------------- #
def test_unknown_thesis_factor_raises(panel: pd.DataFrame) -> None:
    c = ClusterSelectionCombiner(k=5, thesis_weights={"not_a_factor": 1.0})
    with pytest.raises(KeyError):
        c.combine(panel)
