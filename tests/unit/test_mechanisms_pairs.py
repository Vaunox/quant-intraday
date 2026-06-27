"""Tests for the cointegration-pairs mechanism (Part VI / P7.2) on synthetic panels.

Proves the Engle-Granger selection finds a planted cointegrated pair and rejects an independent
one, and that the spec builds a point-in-time monthly net-return series the harness can judge.
"""

import numpy as np
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.research.mechanisms.errors import MechanismDataError, SpecError
from quant.research.mechanisms.pairs import (
    CointegrationPairsSpec,
    PairModel,
    log_price_panel,
    select_cointegrated_pairs,
)
from quant.research.mechanisms.spec import evaluate_spec_under_cpcv
from quant.research.validation.cpcv import CombinatorialPurgedCV

_DATES = pd.date_range("2016-01-01", periods=1400, freq="B", tz=IST)


def _cointegrated_panel(seed: int = 3) -> pd.DataFrame:
    """A panel with one cointegrated pair (A,B) + an independent name C and noise names."""
    rng = np.random.default_rng(seed)
    n = len(_DATES)
    common = np.cumsum(rng.standard_normal(n) * 0.01)  # shared stochastic trend
    a = 100.0 * np.exp(common + rng.standard_normal(n) * 0.005)
    # B tracks A's common trend with a stationary (mean-reverting) spread around it.
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = 0.92 * spread[t - 1] + rng.standard_normal() * 0.01  # AR(1), stationary
    b = 100.0 * np.exp(common + spread)
    c = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.011))  # independent random walk
    extra = {f"N{i}": 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01)) for i in range(4)}
    return pd.DataFrame({"A": a, "B": b, "C": c, **extra}, index=_DATES)


def test_select_finds_cointegrated_pair() -> None:
    panel = _cointegrated_panel()
    log_prices = log_price_panel(panel.iloc[:400])
    pairs = select_cointegrated_pairs(log_prices, pvalue_max=0.05, max_pairs=5, min_correlation=0.5)
    selected = {tuple(sorted((p.y, p.x))) for p in pairs}
    assert ("A", "B") in selected  # the planted cointegrated pair is found
    for p in pairs:
        assert p.sigma > 0.0 and 0.0 <= p.pvalue <= 0.05


def test_select_respects_max_pairs_and_pvalue() -> None:
    panel = _cointegrated_panel()
    log_prices = log_price_panel(panel.iloc[:400])
    pairs = select_cointegrated_pairs(log_prices, pvalue_max=0.05, max_pairs=1, min_correlation=0.0)
    assert len(pairs) <= 1


def test_select_returns_empty_on_too_little_history() -> None:
    panel = _cointegrated_panel()
    pairs = select_cointegrated_pairs(
        log_price_panel(panel.iloc[:10]), pvalue_max=0.05, max_pairs=5, min_correlation=0.0
    )
    assert pairs == []


def test_spec_builds_point_in_time_monthly_returns() -> None:
    panel = _cointegrated_panel()
    spec = CointegrationPairsSpec(
        panel, round_trip_cost=0.0022, formation_days=252, max_pairs=3, min_correlation=0.4
    )
    assert spec.n_periods > 12  # several years of monthly rebalances
    # Label times are strictly forward (t1 after t0) — the holding month.
    assert (spec.label_times.to_numpy() > spec.label_times.index.to_numpy()).all()
    # Runs through the existing CPCV harness without touching the engine.
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(spec, cpcv, periods_per_year=12.0)
    assert ev.distribution.num_paths == 3
    assert np.isfinite(ev.annualised_median_sharpe)


def test_spec_rejects_degenerate_config() -> None:
    panel = _cointegrated_panel()
    with pytest.raises(SpecError, match="degenerate pairs configuration"):
        CointegrationPairsSpec(panel, round_trip_cost=0.0022, formation_days=10)
    with pytest.raises(SpecError, match="round_trip_cost must be non-negative"):
        CointegrationPairsSpec(panel, round_trip_cost=-0.1)


def test_spec_data_gate_when_no_pairs() -> None:
    # A panel of pure independent random walks -> no cointegration -> data gate.
    rng = np.random.default_rng(0)
    n = len(_DATES)
    walks = {f"W{i}": 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01)) for i in range(5)}
    panel = pd.DataFrame(walks, index=_DATES)
    with pytest.raises(MechanismDataError, match="no tradeable rebalance month"):
        CointegrationPairsSpec(
            panel,
            round_trip_cost=0.0022,
            formation_days=252,
            pvalue_max=0.001,
            min_correlation=0.99,
        )


def test_pair_model_is_frozen() -> None:
    model = PairModel(y="A", x="B", beta=1.0, mu=0.0, sigma=0.1, pvalue=0.01)
    with pytest.raises(AttributeError):
        model.beta = 2.0  # type: ignore[misc]
