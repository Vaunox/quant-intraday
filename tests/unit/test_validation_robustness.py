"""Tests for the robustness-battery primitives (P2.8, Deep Dive #2 §4b.7).

These exercise the model-agnostic stress tests with *fake* evaluators (and the real synthetic
price generator), so they are fast and deterministic. The model-coupled end-to-end battery is
tested in ``test_pipeline_robustness.py``; the engine reconciliation in
``test_validation_reconcile.py``.

The contract each test pins: a robust edge survives perturbation/noise/reordering/holdout and
shows no edge on no-signal data, while a fragile one is flagged — the kill-gate's criterion 6.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from quant.data.store import serde
from quant.research.validation.cpcv import PathDistribution
from quant.research.validation.errors import RobustnessError
from quant.research.validation.robustness import (
    EvaluateFn,
    MonteCarloShuffleReport,
    StrategyDataset,
    SyntheticDataReport,
    cross_symbol_validation,
    geometric_brownian_bars,
    max_drawdown,
    monte_carlo_shuffle,
    noise_injection,
    parameter_sensitivity,
    synthetic_data_backtest,
)

IST = ZoneInfo("Asia/Kolkata")


def _index(n: int) -> pd.DatetimeIndex:
    base = datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    return pd.DatetimeIndex([base + timedelta(minutes=15 * i) for i in range(n)], name="event_time")


def _dataset(n: int = 40, *, seed: int = 0) -> StrategyDataset:
    """A small, valid :class:`StrategyDataset` (a learnable 'signal' feature)."""
    rng = np.random.default_rng(seed)
    index = _index(n)
    signal = rng.normal(size=n)
    labels = pd.Series((signal > 0).astype("int64"), index=index)
    features = pd.DataFrame({"signal": signal, "noise": rng.normal(size=n)}, index=index)
    label_times = pd.Series([index[min(i + 1, n - 1)] for i in range(n)], index=index)
    forward = pd.Series(np.where(labels == 1, 0.01, -0.01), index=index)
    regime = pd.DataFrame({"vol_regime": np.abs(rng.normal(1.0, 0.2, n))}, index=index)
    return StrategyDataset(features, labels, label_times, forward, regime)


def _constant_evaluator(median: float) -> EvaluateFn:
    """A fake :data:`EvaluateFn` returning a fixed path-Sharpe distribution."""

    def evaluate(_dataset: StrategyDataset) -> PathDistribution:
        return PathDistribution(np.array([median - 0.1, median, median + 0.1], dtype="float64"))

    return evaluate


# --------------------------------------------------------------------------------------------
# StrategyDataset
# --------------------------------------------------------------------------------------------


def test_strategy_dataset_len_and_feature_names() -> None:
    dataset = _dataset(n=12)
    assert len(dataset) == 12
    assert dataset.feature_names == ("signal", "noise")


def test_strategy_dataset_with_features_shares_the_rest() -> None:
    dataset = _dataset(n=8)
    replaced = dataset.with_features(dataset.features * 2.0)
    assert replaced.labels is dataset.labels
    assert float(replaced.features.to_numpy()[0, 0]) == pytest.approx(
        float(dataset.features.to_numpy()[0, 0]) * 2.0
    )


def test_strategy_dataset_rejects_misaligned_labels() -> None:
    dataset = _dataset(n=8)
    with pytest.raises(RobustnessError, match="share one index"):
        StrategyDataset(
            dataset.features,
            dataset.labels.reset_index(drop=True),
            dataset.label_times,
            dataset.forward_returns,
        )


def test_strategy_dataset_rejects_misaligned_forward_returns() -> None:
    dataset = _dataset(n=8)
    with pytest.raises(RobustnessError, match="forward_returns"):
        StrategyDataset(
            dataset.features,
            dataset.labels,
            dataset.label_times,
            dataset.forward_returns.reset_index(drop=True),
        )


def test_strategy_dataset_rejects_misaligned_regime_features() -> None:
    dataset = _dataset(n=8)
    regime = dataset.regime_features
    assert regime is not None
    with pytest.raises(RobustnessError, match="regime_features"):
        StrategyDataset(
            dataset.features,
            dataset.labels,
            dataset.label_times,
            dataset.forward_returns,
            regime.reset_index(drop=True),
        )


# --------------------------------------------------------------------------------------------
# max_drawdown + Monte Carlo trade shuffle
# --------------------------------------------------------------------------------------------


def test_max_drawdown_hand_computed() -> None:
    # equity path = cumsum([1, -2, 1]) = [1, -1, 0]; peak = [1, 1, 1]; max dd = 1 - (-1) = 2.
    assert max_drawdown(np.array([1.0, -2.0, 1.0])) == pytest.approx(2.0)


def test_max_drawdown_empty_is_zero() -> None:
    assert max_drawdown(np.array([np.nan, np.nan])) == 0.0


def test_monte_carlo_shuffle_brackets_the_observed_drawdown() -> None:
    returns = np.array([0.02, -0.01, 0.03, -0.04, 0.01, -0.02, 0.05, -0.03])
    report = monte_carlo_shuffle(returns, n_shuffles=500, seed=1)
    assert report.n_shuffles == 500
    assert 0.0 <= report.percentile_rank <= 1.0
    # The shuffled distribution must straddle a sensible range and expose its percentiles.
    assert report.shuffled_p05 <= report.shuffled_median <= report.shuffled_p95
    assert isinstance(report.order_robust, bool)


def test_monte_carlo_shuffle_rejects_too_few_returns() -> None:
    with pytest.raises(RobustnessError, match="at least 2 finite returns"):
        monte_carlo_shuffle(np.array([0.01]), n_shuffles=10, seed=1)


def test_monte_carlo_shuffle_rejects_non_positive_shuffles() -> None:
    with pytest.raises(RobustnessError, match="n_shuffles must be >= 1"):
        monte_carlo_shuffle(np.array([0.01, -0.02]), n_shuffles=0, seed=1)


def test_monte_carlo_report_empty_distribution_is_defensive() -> None:
    # The function never produces an empty distribution (n_shuffles >= 1); the guards are
    # exercised directly so the defensive zero-paths are covered.
    report = MonteCarloShuffleReport(
        observed_max_drawdown=0.0, shuffled_drawdowns=np.array([], dtype="float64"), n_shuffles=0
    )
    assert report.percentile_rank == 0.0
    assert report.shuffled_median == 0.0
    assert report.shuffled_p05 == 0.0
    assert report.shuffled_p95 == 0.0


# --------------------------------------------------------------------------------------------
# Parameter sensitivity
# --------------------------------------------------------------------------------------------


def test_parameter_sensitivity_flags_a_robust_edge_as_safe() -> None:
    variants = {
        "baseline": _constant_evaluator(1.0),
        "v2": _constant_evaluator(0.95),
        "v3": _constant_evaluator(1.05),
    }
    report = parameter_sensitivity(
        variants, _dataset(), baseline_key="baseline", knife_edge_cv_threshold=1.0
    )
    assert report.baseline_median == pytest.approx(1.0)
    assert not report.is_knife_edge
    assert not report.flips_sign
    assert report.spread == pytest.approx(0.1, abs=1e-9)


def test_parameter_sensitivity_flags_sign_flip_as_knife_edge() -> None:
    variants = {"baseline": _constant_evaluator(1.0), "fragile": _constant_evaluator(-0.5)}
    report = parameter_sensitivity(
        variants, _dataset(), baseline_key="baseline", knife_edge_cv_threshold=10.0
    )
    assert report.flips_sign
    assert report.is_knife_edge  # a positive baseline that flips negative is overfit


def test_parameter_sensitivity_flags_high_variance_as_knife_edge() -> None:
    variants = {"baseline": _constant_evaluator(2.0), "wild": _constant_evaluator(0.1)}
    report = parameter_sensitivity(
        variants, _dataset(), baseline_key="baseline", knife_edge_cv_threshold=0.1
    )
    assert report.coefficient_of_variation > 0.1
    assert report.is_knife_edge


def test_parameter_sensitivity_zero_mean_cv_is_zero() -> None:
    # Symmetric medians around zero => mean ~ 0 => the CV guard returns 0.0 (no blow-up).
    variants = {"baseline": _constant_evaluator(0.5), "mirror": _constant_evaluator(-0.5)}
    report = parameter_sensitivity(
        variants, _dataset(), baseline_key="baseline", knife_edge_cv_threshold=1.0
    )
    assert report.coefficient_of_variation == 0.0


def test_parameter_sensitivity_requires_baseline_and_a_perturbation() -> None:
    with pytest.raises(RobustnessError, match=">= 1 perturbation"):
        parameter_sensitivity(
            {"only": _constant_evaluator(1.0)},
            _dataset(),
            baseline_key="only",
            knife_edge_cv_threshold=1.0,
        )
    with pytest.raises(RobustnessError, match="not among the variants"):
        parameter_sensitivity(
            {"a": _constant_evaluator(1.0), "b": _constant_evaluator(1.0)},
            _dataset(),
            baseline_key="missing",
            knife_edge_cv_threshold=1.0,
        )


# --------------------------------------------------------------------------------------------
# Noise injection
# --------------------------------------------------------------------------------------------


def test_noise_injection_reports_decay_and_edge_persistence() -> None:
    # A fake evaluator whose median falls as the features' dispersion grows (noise added).
    def evaluate(dataset: StrategyDataset) -> PathDistribution:
        spread = float(dataset.features["signal"].std(ddof=0))
        median = max(1.5 - spread, -1.0)
        return PathDistribution(np.array([median, median, median], dtype="float64"))

    report = noise_injection(evaluate, _dataset(), noise_levels=[0.1, 1.0], repeats=2, seed=3)
    assert report.levels == (0.1, 1.0)
    assert report.baseline_median > report.median_by_level[1.0]  # more noise -> lower edge
    assert isinstance(report.edge_persists, bool)


def test_noise_injection_edge_persists_when_baseline_non_positive() -> None:
    report = noise_injection(
        _constant_evaluator(-0.5), _dataset(), noise_levels=[0.1], repeats=1, seed=1
    )
    assert report.baseline_median < 0.0
    assert report.edge_persists  # a non-positive baseline trivially "persists" (nothing to lose)


def test_noise_injection_validates_inputs() -> None:
    dataset = _dataset()
    with pytest.raises(RobustnessError, match="at least one noise level"):
        noise_injection(_constant_evaluator(1.0), dataset, noise_levels=[], repeats=1, seed=1)
    with pytest.raises(RobustnessError, match="non-negative"):
        noise_injection(_constant_evaluator(1.0), dataset, noise_levels=[-0.1], repeats=1, seed=1)
    with pytest.raises(RobustnessError, match="repeats must be >= 1"):
        noise_injection(_constant_evaluator(1.0), dataset, noise_levels=[0.1], repeats=0, seed=1)


# --------------------------------------------------------------------------------------------
# Cross-symbol validation
# --------------------------------------------------------------------------------------------


def test_cross_symbol_validation_flags_a_generalizing_signal() -> None:
    datasets = {"AAA": _dataset(seed=1), "BBB": _dataset(seed=2), "CCC": _dataset(seed=3)}

    def score(_train: Sequence[StrategyDataset], test: StrategyDataset) -> pd.Series:
        rng = np.random.default_rng(0)
        return pd.Series(
            0.01 + rng.normal(0.0, 0.001, len(test)), index=test.features.index
        )  # uniformly profitable held-out returns

    report = cross_symbol_validation(datasets, score)
    assert report.symbols == ("AAA", "BBB", "CCC")
    assert report.fraction_positive == 1.0
    assert report.median > 0.0
    assert report.generalizes


def test_cross_symbol_validation_flags_a_non_generalizing_signal() -> None:
    datasets = {"AAA": _dataset(seed=1), "BBB": _dataset(seed=2)}

    def score(_train: Sequence[StrategyDataset], test: StrategyDataset) -> pd.Series:
        rng = np.random.default_rng(0)
        return pd.Series(-0.01 + rng.normal(0.0, 0.001, len(test)), index=test.features.index)

    report = cross_symbol_validation(datasets, score)
    assert report.fraction_positive == 0.0
    assert not report.generalizes


def test_cross_symbol_validation_annualizes_when_asked() -> None:
    datasets = {"AAA": _dataset(seed=1), "BBB": _dataset(seed=2)}

    def score(_train: Sequence[StrategyDataset], test: StrategyDataset) -> pd.Series:
        rng = np.random.default_rng(0)
        return pd.Series(0.01 + rng.normal(0.0, 0.001, len(test)), index=test.features.index)

    plain = cross_symbol_validation(datasets, score)
    annual = cross_symbol_validation(datasets, score, periods_per_year=252.0)
    assert annual.median > plain.median  # annualization scales the per-observation Sharpe up


def test_cross_symbol_validation_requires_two_symbols() -> None:
    with pytest.raises(RobustnessError, match="at least two symbols"):
        cross_symbol_validation({"AAA": _dataset()}, lambda _t, _x: pd.Series([0.01]))


def test_cross_symbol_validation_rejects_empty_score() -> None:
    datasets = {"AAA": _dataset(seed=1), "BBB": _dataset(seed=2)}
    with pytest.raises(RobustnessError, match="no returns"):
        cross_symbol_validation(
            datasets, lambda _t, x: pd.Series(dtype="float64", index=x.features.index[:0])
        )


# --------------------------------------------------------------------------------------------
# Synthetic-data backtest
# --------------------------------------------------------------------------------------------


def test_synthetic_data_backtest_centres_near_zero_on_no_signal() -> None:
    # A fake recipe with no real edge: each universe's median is ~ N(0, small).
    rng = np.random.default_rng(0)

    def generate(seed: int) -> Mapping[str, pd.DataFrame]:
        return {
            "SYN": geometric_brownian_bars("SYN", sessions=2, minutes_per_session=30, seed=seed)
        }

    def build(_bars: Mapping[str, pd.DataFrame]) -> StrategyDataset:
        return _dataset(seed=int(rng.integers(0, 1_000_000)))

    def evaluate(_dataset: StrategyDataset) -> PathDistribution:
        return PathDistribution(np.array([rng.normal(0.0, 0.05), 0.0, 0.0], dtype="float64"))

    report = synthetic_data_backtest(
        generate, build, evaluate, n_universes=6, seed=1, edge_threshold=0.5
    )
    assert report.n_universes == 6
    assert report.n_skipped == 0
    assert abs(report.mean_median) < 0.5
    assert not report.edge_detected


def test_synthetic_data_backtest_detects_a_spurious_edge() -> None:
    def generate(seed: int) -> Mapping[str, pd.DataFrame]:
        return {
            "SYN": geometric_brownian_bars("SYN", sessions=1, minutes_per_session=20, seed=seed)
        }

    def build(_bars: Mapping[str, pd.DataFrame]) -> StrategyDataset:
        return _dataset()

    report = synthetic_data_backtest(
        generate, build, _constant_evaluator(1.5), n_universes=3, seed=1, edge_threshold=0.5
    )
    assert report.mean_median > 0.5
    assert report.edge_detected  # a strong edge on no-signal data is a methodology leak


def test_synthetic_data_backtest_skips_empty_universes() -> None:
    built: list[int] = []

    def generate(seed: int) -> Mapping[str, pd.DataFrame]:
        return {
            "SYN": geometric_brownian_bars("SYN", sessions=1, minutes_per_session=20, seed=seed)
        }

    def build(_bars: Mapping[str, pd.DataFrame]) -> StrategyDataset:
        built.append(1)
        # First universe yields events, the rest are empty (no labellable event).
        return _dataset() if len(built) == 1 else _empty_dataset()

    report = synthetic_data_backtest(
        generate, build, _constant_evaluator(0.1), n_universes=3, seed=1, edge_threshold=0.5
    )
    assert report.n_skipped == 2
    assert report.median_sharpes.shape == (1,)


def test_synthetic_data_backtest_validates_inputs() -> None:
    def generate(seed: int) -> Mapping[str, pd.DataFrame]:
        return {
            "SYN": geometric_brownian_bars("SYN", sessions=1, minutes_per_session=20, seed=seed)
        }

    with pytest.raises(RobustnessError, match="n_universes must be >= 1"):
        synthetic_data_backtest(
            generate,
            lambda _b: _dataset(),
            _constant_evaluator(0.1),
            n_universes=0,
            seed=1,
            edge_threshold=0.5,
        )
    with pytest.raises(RobustnessError, match="every synthetic universe produced no events"):
        synthetic_data_backtest(
            generate,
            lambda _b: _empty_dataset(),
            _constant_evaluator(0.1),
            n_universes=2,
            seed=1,
            edge_threshold=0.5,
        )


def test_synthetic_report_empty_is_defensive() -> None:
    report = SyntheticDataReport(
        median_sharpes=np.array([], dtype="float64"), n_universes=0, n_skipped=0, edge_threshold=0.5
    )
    assert report.mean_median == 0.0
    assert report.fraction_positive == 0.0
    assert not report.edge_detected


# --------------------------------------------------------------------------------------------
# Synthetic price generator
# --------------------------------------------------------------------------------------------


def test_geometric_brownian_bars_matches_the_canonical_schema() -> None:
    bars = geometric_brownian_bars("SYN", sessions=3, minutes_per_session=40, seed=7)
    # Validates against the canonical bars schema (raises if not), and one IST session/day.
    serde.ensure_bars_schema(bars)
    assert len(bars) == 120
    assert (bars["high"] >= bars["close"]).all() and (bars["low"] <= bars["close"]).all()
    days = pd.DatetimeIndex(bars["timestamp"]).tz_convert(IST).normalize().nunique()
    assert days == 3


def test_geometric_brownian_bars_is_deterministic() -> None:
    a = geometric_brownian_bars("SYN", sessions=2, minutes_per_session=30, seed=11)
    b = geometric_brownian_bars("SYN", sessions=2, minutes_per_session=30, seed=11)
    pd.testing.assert_frame_equal(a, b)


def test_geometric_brownian_bars_single_session() -> None:
    # The single-block branch of the timestamp builder (sessions=1).
    bars = geometric_brownian_bars("SYN", sessions=1, minutes_per_session=10, seed=1)
    assert len(bars) == 10


def test_geometric_brownian_bars_validates_inputs() -> None:
    with pytest.raises(RobustnessError, match="must be positive"):
        geometric_brownian_bars("SYN", sessions=0, minutes_per_session=10, seed=1)
    with pytest.raises(RobustnessError, match="sigma and start_price"):
        geometric_brownian_bars("SYN", sessions=1, minutes_per_session=10, seed=1, sigma=0.0)


def _empty_dataset() -> StrategyDataset:
    index = pd.DatetimeIndex([], name="event_time")
    return StrategyDataset(
        features=pd.DataFrame(index=index),
        labels=pd.Series(dtype="int64", index=index),
        label_times=pd.Series(dtype="datetime64[ns, Asia/Kolkata]", index=index),
        forward_returns=pd.Series(dtype="float64", index=index),
    )
