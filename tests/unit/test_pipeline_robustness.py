"""Tests for the P2.8 robustness-battery orchestration (the model wired into the battery).

The end-to-end test drives the *real* P2.7 stack (ensemble + regime gate + registry) through the
full battery on a small two-symbol synthetic universe with reduced robustness knobs, asserting
the acceptance criterion — *"each test runs and reports; two engines reconcile within tolerance"*.
The targeted tests pin the orchestration's helper branches (artifact loading, per-symbol
assembly, the synthetic builder, the empty sample-strategy path).
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from quant.core.config import Config
from quant.research.models.registry import FileModelRegistry, InMemoryModelRegistry
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.errors import PipelineError
from quant.research.pipeline.final_run import train_final_model
from quant.research.pipeline.robustness import (
    RobustnessBatteryReport,
    _load_artifact,
    _per_symbol_datasets,
    build_strategy_evaluator,
    reconcile_sample_strategy,
    run_robustness_battery,
    sensitivity_variants,
    strategy_dataset_builder,
    synthetic_universe_generator,
)
from tests.unit.pipeline_fakes import FakeRepository, flat_bars, minute_bars, pipeline_config

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2024, 1, 1, tzinfo=IST)
END = datetime(2024, 12, 31, tzinfo=IST)


def _fast_config() -> Config:
    """A small, fast config with reduced robustness knobs (a CI-sized battery)."""
    config = pipeline_config()
    rob = config.robustness.model_copy(
        update={
            "cpcv_groups": 4,
            "cpcv_test_groups": 1,
            "cpcv_embargo_pct": 0.0,
            "noise_levels": (0.1,),
            "noise_repeats": 1,
            "monte_carlo_shuffles": 25,
            "synthetic_universes": 1,
            "synthetic_sessions": 8,
            "reconcile_tolerance_inr": 1e-6,
            "random_seed": 7,
        }
    )
    return config.model_copy(update={"robustness": rob})


def _repo() -> FakeRepository:
    return FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=40, minutes=120, seed=1, drift=0.00006),
            "BBB": minute_bars("BBB", sessions=40, minutes=120, seed=2, drift=-0.00004),
        }
    )


def _register_artifact(config: Config, repo: FakeRepository, root: Path) -> FileModelRegistry:
    registry = FileModelRegistry(root)
    train_final_model(
        config,
        repo,
        ["AAA", "BBB"],
        START,
        END,
        registry=registry,
        tracker=InMemoryExperimentTracker(),
    )
    return registry


# --------------------------------------------------------------------------------------------
# End-to-end: every stress test runs and reports; the engines reconcile
# --------------------------------------------------------------------------------------------


def test_run_robustness_battery_end_to_end(tmp_path: Path) -> None:
    config = _fast_config()
    repo = _repo()
    registry = _register_artifact(config, repo, tmp_path / "registry")
    tracker = InMemoryExperimentTracker()

    report = run_robustness_battery(
        config, repo, ["AAA", "BBB"], START, END, registry=registry, tracker=tracker
    )

    # The artifact P2A.6-style run produced is the input the battery validated.
    assert report.model_id == "ensemble-regime-v1-0001"
    assert report.symbols == ("AAA", "BBB")
    assert report.n_obs > 0

    # Each of the five §4b.7 stress tests produced a report (the acceptance criterion).
    assert report.parameter_sensitivity.baseline_key == "baseline"
    assert set(report.noise_injection.levels) == {0.1}
    assert report.monte_carlo.n_shuffles == 25
    assert report.cross_symbol.symbols == ("AAA", "BBB")
    assert report.synthetic.n_universes == 1
    assert isinstance(report.passes, bool)

    # The headline: the two engines reconcile within tolerance on the sample strategy.
    assert report.reconciliation.reconciled
    assert report.reconciliation.max_money_diff < config.robustness.reconcile_tolerance_inr

    # Every stress variant was logged as its own run (the honest trial count for P2.9).
    expected_runs = (
        len(report.parameter_sensitivity.median_by_variant)
        + len(report.noise_injection.median_by_level)
        + 4  # monte-carlo + cross-symbol + synthetic + reconciliation
    )
    assert len(tracker.runs) == expected_runs
    assert any(run.params.get("test") == "parameter_sensitivity" for run in tracker.runs)


# --------------------------------------------------------------------------------------------
# Targeted branch coverage
# --------------------------------------------------------------------------------------------


def test_sensitivity_variants_drops_zero_regime_perturbation() -> None:
    config = pipeline_config()
    one_regime = config.model_copy(
        update={"pipeline": config.pipeline.model_copy(update={"n_regimes": 1})}
    )
    variants = sensitivity_variants(one_regime)
    assert "baseline" in variants
    assert "n_regimes=2" in variants  # n_regimes + 1 is always present
    assert "n_regimes=0" not in variants  # n_regimes - 1 < 1 is dropped, never a 0-regime GMM


def test_build_strategy_evaluator_ungated_runs(tmp_path: Path) -> None:
    # The ungated evaluator path (regime gate off) must still produce a distribution.
    config = _fast_config()
    repo = _repo()
    from quant.research.pipeline.robustness import _per_symbol_datasets as per_symbol

    datasets = per_symbol(config, repo, ["AAA", "BBB"], START, END)
    evaluate = build_strategy_evaluator(config, gated=False)
    distribution = evaluate(next(iter(datasets.values())))
    assert distribution.num_paths >= 1


def test_strategy_dataset_builder_empty_universe_maps_to_empty() -> None:
    config = _fast_config()
    builder = strategy_dataset_builder(config)
    # Flat bars never trigger a CUSUM event -> no labellable rows -> an empty dataset.
    dataset = builder({"FLAT": flat_bars("FLAT", sessions=3)})
    assert len(dataset) == 0


def test_synthetic_universe_generator_is_seeded() -> None:
    config = _fast_config()
    generate = synthetic_universe_generator(config, n_symbols=2)
    universe = generate(1)
    assert set(universe) == {"SYN0", "SYN1"}
    # Deterministic in the seed.
    again = synthetic_universe_generator(config, n_symbols=2)(1)
    pd.testing.assert_frame_equal(universe["SYN0"], again["SYN0"])


def test_reconcile_sample_strategy_with_no_events_is_flat(tmp_path: Path) -> None:
    # A symbol whose flat bars yield no events -> empty target path -> the engines reconcile
    # trivially (both flat). The artifact is never consulted (the empty-targets short-circuit).
    config = _fast_config()
    repo = FakeRepository({"FLAT": flat_bars("FLAT", sessions=4)})
    report = reconcile_sample_strategy(config, object(), repo, "FLAT", START, END)  # type: ignore[arg-type]
    assert report.reconciled
    assert report.primary_fills == 0


def test_per_symbol_datasets_requires_two_symbols() -> None:
    config = _fast_config()
    repo = FakeRepository({"AAA": minute_bars("AAA", sessions=30, minutes=120, seed=1)})
    with pytest.raises(PipelineError, match=">= 2 symbols"):
        _per_symbol_datasets(config, repo, ["AAA"], START, END)


def test_per_symbol_datasets_skips_empty_and_eventless_symbols() -> None:
    config = _fast_config()
    repo = FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=30, minutes=120, seed=1, drift=0.00006),
            "BBB": minute_bars("BBB", sessions=30, minutes=120, seed=2, drift=-0.00004),
            "FLAT": flat_bars("FLAT", sessions=4),  # eventless -> skipped
        }
    )
    # MISSING returns empty bars (not in the repo) -> the empty-bars skip branch.
    datasets = _per_symbol_datasets(config, repo, ["AAA", "BBB", "FLAT", "MISSING"], START, END)
    assert set(datasets) == {"AAA", "BBB"}


def test_load_artifact_missing_raises() -> None:
    config = _fast_config()
    with pytest.raises(PipelineError, match="no artifact registered"):
        _load_artifact(config, InMemoryModelRegistry())


def test_load_artifact_wrong_type_raises() -> None:
    config = _fast_config()
    registry = InMemoryModelRegistry()
    registry.register(
        {"not": "a model"},
        model_version=config.pipeline.registry_model_version,
        data_version="d",
        feature_set_version="f",
        label_version="l",
    )
    with pytest.raises(PipelineError, match="expected GatedEnsembleModel"):
        _load_artifact(config, registry)


def test_report_passes_is_a_summary_of_all_tests() -> None:
    # Build a report whose sub-flags are all favourable -> passes True (the summary logic).
    import numpy as np

    from quant.research.validation.reconcile import ReconciliationReport
    from quant.research.validation.robustness import (
        CrossSymbolReport,
        MonteCarloShuffleReport,
        NoiseInjectionReport,
        ParameterSensitivityReport,
        SyntheticDataReport,
    )

    report = RobustnessBatteryReport(
        model_id="m-0001",
        data_version="d",
        label_version="l",
        feature_set_version="f",
        n_obs=100,
        symbols=("AAA",),
        parameter_sensitivity=ParameterSensitivityReport(
            "baseline", {"baseline": 1.0, "v": 0.95}, 1.0
        ),
        noise_injection=NoiseInjectionReport(1.0, {0.1: 0.9}),
        monte_carlo=MonteCarloShuffleReport(0.1, np.array([0.05, 0.15, 0.2]), 3),
        cross_symbol=CrossSymbolReport({"AAA": 0.5, "BBB": 0.6}),
        synthetic=SyntheticDataReport(np.array([0.0, 0.05]), 2, 0, 0.5),
        reconciliation=ReconciliationReport(10, 2, 2, 0.0, 0.0, 0.0, 1e-9, 1e-6),
    )
    assert report.passes
