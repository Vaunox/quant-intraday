"""Run the robustness battery against the real, registered strategy (P2.8 orchestration).

The battery primitives live in :mod:`quant.research.validation.robustness` /
:mod:`quant.research.validation.reconcile` and take the model as an injected callable so they
stay model-agnostic. This module is the layer that supplies the concrete model — exactly as
:mod:`quant.research.pipeline.final_run` is the layer that wires the model into training — and
runs all five §4b.7 stress tests plus the two-engine reconciliation against the artifact P2A.6
registered, logging every variant tried as its own tracker run (the honest trial count P2.9's
Deflated Sharpe needs).

The battery stresses the **recipe** that produced the artifact — the cross-family ensemble +
regime gate, re-fit out-of-sample per CPCV split under perturbation — because *"is the edge
real?"* cannot be answered by scoring one frozen model; it is answered by asking whether the
approach keeps its edge when parameters wobble, features are noised, trades are reordered, names
are held out, and the data carries no real signal. The reconciliation, in contrast, drives the
**frozen artifact's** own signal through both backtest engines.

Every model run here re-uses the merged P2.6/P2.7 code unmodified (Ground Rule 4): the shared
:func:`~quant.research.models.estimators.cross_family_estimators` stack, the OOF ensemble
builder, and the CPCV evaluator. It adds no model maths.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from quant.core.config import Config
from quant.core.interfaces import Repository
from quant.core.logging import get_logger
from quant.research.models.ensemble import build_ensemble
from quant.research.models.estimators import cross_family_estimators
from quant.research.models.evaluation import (
    evaluate_ensemble_under_cpcv,
    probability_to_position,
)
from quant.research.models.registry import ModelRegistry
from quant.research.models.tracking import ExperimentTracker, RunRecord
from quant.research.pipeline.dataset import (
    PooledDataset,
    SymbolDataset,
    build_pooled_dataset,
    build_symbol_dataset,
    data_version,
    label_version,
    pool_datasets,
    resample_bars,
)
from quant.research.pipeline.errors import PipelineError
from quant.research.pipeline.model import GatedEnsembleModel
from quant.research.validation.backtest import create_backtester
from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution
from quant.research.validation.reconcile import (
    ReconciliationReport,
    create_vectorized_backtester,
    reconcile_engines,
)
from quant.research.validation.robustness import (
    CrossSymbolReport,
    CrossSymbolScoreFn,
    DatasetBuilder,
    EvaluateFn,
    MonteCarloShuffleReport,
    NoiseInjectionReport,
    ParameterSensitivityReport,
    StrategyDataset,
    SyntheticDataReport,
    UniverseGenerator,
    cross_symbol_validation,
    geometric_brownian_bars,
    monte_carlo_shuffle,
    noise_injection,
    parameter_sensitivity,
    synthetic_data_backtest,
)

_logger = get_logger(__name__)

#: The unperturbed variant's key in the parameter-sensitivity grid.
BASELINE_VARIANT = "baseline"
#: Number of synthetic symbols simulated per no-real-luck universe (enough to pool a CPCV).
_SYNTHETIC_SYMBOLS = 4
#: Minutes per simulated session (~ NSE 09:15-15:30); resampled to the decision clock.
_SYNTHETIC_SESSION_MINUTES = 375


@dataclass(frozen=True, slots=True)
class RobustnessBatteryReport:
    """The consolidated P2.8 verdict: the five stress tests + the two-engine reconciliation.

    ``passes`` is the battery's *own* summary (kill-gate criterion 6 is emitted by P2.9, which
    consumes these). On a genuinely weak edge most flags will be ``False`` — the honest expected
    outcome (Inviolable Rule 7), not a bug.
    """

    model_id: str | None
    data_version: str
    label_version: str
    feature_set_version: str
    n_obs: int
    symbols: tuple[str, ...]
    parameter_sensitivity: ParameterSensitivityReport
    noise_injection: NoiseInjectionReport
    monte_carlo: MonteCarloShuffleReport
    cross_symbol: CrossSymbolReport
    synthetic: SyntheticDataReport
    reconciliation: ReconciliationReport

    @property
    def passes(self) -> bool:
        """Whether the strategy clears every stress test and the engines reconcile."""
        return (
            not self.parameter_sensitivity.is_knife_edge
            and self.noise_injection.edge_persists
            and self.monte_carlo.order_robust
            and self.cross_symbol.generalizes
            and not self.synthetic.edge_detected
            and self.reconciliation.reconciled
        )


# --------------------------------------------------------------------------------------------
# Strategy evaluators (the model wired into the battery's injected callables)
# --------------------------------------------------------------------------------------------


def build_strategy_evaluator(
    config: Config,
    *,
    method: str | None = None,
    n_regimes: int | None = None,
    embargo_pct: float | None = None,
    gated: bool = True,
) -> EvaluateFn:
    """Return an :data:`EvaluateFn`: evaluate the ensemble (+regime gate) under CPCV on a dataset.

    The defaults reproduce the shipped recipe (``config.pipeline`` blend/regimes,
    ``config.robustness`` CPCV scheme); the keyword overrides are what the parameter-sensitivity
    grid perturbs. ``gated=False`` runs the ensemble ungated (the regime gate switched off).
    """
    estimators = cross_family_estimators(config.model)
    blend = method or config.pipeline.ensemble_method
    regimes = config.pipeline.n_regimes if n_regimes is None else n_regimes
    embargo = config.robustness.cpcv_embargo_pct if embargo_pct is None else embargo_pct
    cpcv = CombinatorialPurgedCV(
        config.robustness.cpcv_groups, config.robustness.cpcv_test_groups, embargo_pct=embargo
    )

    def evaluate(dataset: StrategyDataset) -> PathDistribution:
        return evaluate_ensemble_under_cpcv(
            estimators,
            dataset.features,
            dataset.labels,
            dataset.label_times,
            dataset.forward_returns,
            cpcv,
            regime_features=dataset.regime_features if gated else None,
            n_regimes=regimes,
            method=blend,
            random_seed=config.model.random_seed,
        ).distribution

    return evaluate


def sensitivity_variants(config: Config) -> dict[str, EvaluateFn]:
    """The parameter-sensitivity grid: the baseline plus small, single-knob perturbations (§4b.7).

    Perturbs the blend method, the regime-gate on/off and component count, and the CPCV embargo —
    each a parameter a knife-edge fit would be brittle to. A robust edge survives all of them.
    """
    blend = config.pipeline.ensemble_method
    other_blend = "stack" if blend == "rank_average" else "rank_average"
    regimes = config.pipeline.n_regimes
    variants: dict[str, EvaluateFn] = {
        BASELINE_VARIANT: build_strategy_evaluator(config),
        f"method={other_blend}": build_strategy_evaluator(config, method=other_blend),
        "ungated": build_strategy_evaluator(config, gated=False),
        "embargo=0": build_strategy_evaluator(config, embargo_pct=0.0),
        f"n_regimes={regimes + 1}": build_strategy_evaluator(config, n_regimes=regimes + 1),
    }
    if regimes - 1 >= 1:
        variants[f"n_regimes={regimes - 1}"] = build_strategy_evaluator(
            config, n_regimes=regimes - 1
        )
    return variants


def cross_symbol_score(config: Config) -> CrossSymbolScoreFn:
    """Return the cross-symbol scorer: fit the ensemble on the train symbols, score the held-out.

    Fits a single (in-sample-combined) ensemble on the pooled training symbols, then turns the
    held-out symbol's calibrated probabilities into positions and multiplies by its realised
    forward returns — the held-out symbol's out-of-sample per-event strategy return.
    """
    estimators = cross_family_estimators(config.model)
    blend = config.pipeline.ensemble_method

    def score(
        train_datasets: Sequence[StrategyDataset], test_dataset: StrategyDataset
    ) -> pd.Series:
        train_features = pd.concat([d.features for d in train_datasets], ignore_index=True)
        train_labels = pd.concat([d.labels for d in train_datasets], ignore_index=True)
        model = build_ensemble(estimators, train_features, train_labels, method=blend)
        position = probability_to_position(model.predict_proba(test_dataset.features))
        returns = position * test_dataset.forward_returns.to_numpy(dtype="float64")
        return pd.Series(returns, index=test_dataset.features.index, name="strategy_return")

    return score


def synthetic_universe_generator(
    config: Config, *, n_symbols: int = _SYNTHETIC_SYMBOLS
) -> UniverseGenerator:
    """Return a generator of no-real-luck universes: ``n_symbols`` driftless GBM symbols/seed."""

    def generate(seed: int) -> Mapping[str, pd.DataFrame]:
        return {
            f"SYN{i}": geometric_brownian_bars(
                f"SYN{i}",
                sessions=config.robustness.synthetic_sessions,
                minutes_per_session=_SYNTHETIC_SESSION_MINUTES,
                seed=seed * n_symbols + i,
            )
            for i in range(n_symbols)
        }

    return generate


def strategy_dataset_builder(config: Config) -> DatasetBuilder:
    """Return a builder turning a universe of bars into a pooled :class:`StrategyDataset`.

    The same feature/label/pool pipeline the real run uses (:mod:`quant.research.pipeline.dataset`),
    so the synthetic-data backtest stresses the genuine recipe. A universe that yields no
    labellable events maps to an empty dataset (the battery skips it).
    """

    def build(bars_by_symbol: Mapping[str, pd.DataFrame]) -> StrategyDataset:
        datasets = []
        for symbol, bars in bars_by_symbol.items():
            dataset = build_symbol_dataset(symbol, bars, config)
            if len(dataset) > 0:
                datasets.append(dataset)
        if not datasets:
            return _empty_strategy_dataset()
        pooled = pool_datasets(datasets, gap=pd.Timedelta(days=config.pipeline.pool_gap_days))
        return _pooled_to_strategy_dataset(pooled)

    return build


# --------------------------------------------------------------------------------------------
# The battery runner
# --------------------------------------------------------------------------------------------


def run_robustness_battery(
    config: Config,
    repository: Repository,
    symbols: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    registry: ModelRegistry,
    tracker: ExperimentTracker,
    run_name: str = "p2.8-robustness",
) -> RobustnessBatteryReport:
    """Run the full §4b.7 battery + two-engine reconciliation against the registered artifact.

    Args:
        config: System config (model/pipeline/robustness knobs).
        repository: The store the real bars are read from (Parquet archive, by default).
        symbols: The universe symbols (the same pooled into the P2A.6 artifact).
        start: Inclusive window start (tz-aware IST).
        end: Inclusive window end (tz-aware IST).
        registry: Where the P2A.6 artifact lives (its latest version is reconciled).
        tracker: Where each stress variant is logged as a run (persistent MLflow for the real
            run — the honest trial count for P2.9's DSR; in-memory in tests).
        run_name: Base name for the logged runs.

    Returns:
        The consolidated :class:`RobustnessBatteryReport`.

    Raises:
        PipelineError: If no symbol produced labellable events, or no artifact is registered
            under ``config.pipeline.registry_model_version``.
    """
    pooled = build_pooled_dataset(config, repository, symbols, start, end)
    dataset = _pooled_to_strategy_dataset(pooled)
    per_symbol = _per_symbol_datasets(config, repository, symbols, start, end)
    rob = config.robustness

    sensitivity = parameter_sensitivity(
        sensitivity_variants(config),
        dataset,
        baseline_key=BASELINE_VARIANT,
        knife_edge_cv_threshold=rob.knife_edge_cv_threshold,
    )
    baseline_paths = _baseline_paths(config, dataset)
    monte_carlo = monte_carlo_shuffle(
        baseline_paths, n_shuffles=rob.monte_carlo_shuffles, seed=rob.random_seed
    )
    noise = noise_injection(
        build_strategy_evaluator(config),
        dataset,
        noise_levels=rob.noise_levels,
        repeats=rob.noise_repeats,
        seed=rob.random_seed,
    )
    cross = cross_symbol_validation(per_symbol, cross_symbol_score(config))
    synthetic = synthetic_data_backtest(
        synthetic_universe_generator(config),
        strategy_dataset_builder(config),
        build_strategy_evaluator(config),
        n_universes=rob.synthetic_universes,
        seed=rob.random_seed,
        edge_threshold=rob.synthetic_edge_threshold,
    )

    artifact, model_id = _load_artifact(config, registry)
    reconciliation = reconcile_sample_strategy(config, artifact, repository, symbols[0], start, end)

    report = RobustnessBatteryReport(
        model_id=model_id,
        data_version=data_version(
            symbols, start, end, f"{config.market.decision_frequency_minutes}min"
        ),
        label_version=label_version(config.labeling),
        feature_set_version=config.features.feature_set_version,
        n_obs=pooled.n_obs,
        symbols=pooled.symbols,
        parameter_sensitivity=sensitivity,
        noise_injection=noise,
        monte_carlo=monte_carlo,
        cross_symbol=cross,
        synthetic=synthetic,
        reconciliation=reconciliation,
    )
    _log_battery(tracker, run_name, report)
    _logger.info(
        "robustness battery complete",
        extra={
            "model_id": model_id,
            "passes": report.passes,
            "n_obs": report.n_obs,
            "knife_edge": sensitivity.is_knife_edge,
            "edge_persists": noise.edge_persists,
            "cross_symbol_generalizes": cross.generalizes,
            "synthetic_edge_detected": synthetic.edge_detected,
            "reconciled": reconciliation.reconciled,
        },
    )
    return report


def reconcile_sample_strategy(
    config: Config,
    artifact: GatedEnsembleModel,
    repository: Repository,
    symbol: str,
    start: datetime,
    end: datetime,
) -> ReconciliationReport:
    """Drive the artifact's signal on one real symbol through both engines and reconcile them.

    The sample strategy is the artifact's regime-gated position turned into integer shares by a
    crude placeholder sizer (full conviction ~ 1x capital in the name; real sizing is P3.4) — the
    reconciliation only needs a non-trivial integer target path to drive identical fills through
    the event-driven and the vectorised engines.
    """
    bars = repository.read_bars(symbol, start, end)
    decision_bars = resample_bars(bars, config.market.decision_frequency_minutes)
    targets = _sample_targets(config, artifact, symbol, bars, decision_bars)
    return reconcile_engines(
        decision_bars,
        targets,
        primary=create_backtester(config),
        secondary=create_vectorized_backtester(config),
        tolerance=config.robustness.reconcile_tolerance_inr,
    )


def _sample_targets(
    config: Config,
    artifact: GatedEnsembleModel,
    symbol: str,
    bars: pd.DataFrame,
    decision_bars: pd.DataFrame,
) -> pd.Series:
    """Build integer share targets from the artifact's gated position at each event bar."""
    dataset = build_symbol_dataset(symbol, bars, config)
    if len(dataset) == 0:
        return pd.Series(dtype="int64", index=pd.DatetimeIndex([], name="timestamp"))
    gated = artifact.gated_position(dataset.features, dataset.regime_features)
    close = decision_bars.set_index("timestamp")["close"].reindex(dataset.features.index).to_numpy()
    capital = config.backtest.initial_capital_inr
    shares = np.nan_to_num(np.round(gated * capital / close)).astype("int64")
    targets = pd.Series(shares, index=dataset.features.index, name="target")
    return targets[targets != 0]


def _baseline_paths(config: Config, dataset: StrategyDataset) -> np.ndarray:
    """Return the baseline strategy's first reconstructed CPCV path (for the trade shuffle)."""
    estimators = cross_family_estimators(config.model)
    cpcv = CombinatorialPurgedCV(
        config.robustness.cpcv_groups,
        config.robustness.cpcv_test_groups,
        embargo_pct=config.robustness.cpcv_embargo_pct,
    )
    evaluation = evaluate_ensemble_under_cpcv(
        estimators,
        dataset.features,
        dataset.labels,
        dataset.label_times,
        dataset.forward_returns,
        cpcv,
        regime_features=dataset.regime_features,
        n_regimes=config.pipeline.n_regimes,
        method=config.pipeline.ensemble_method,
        random_seed=config.model.random_seed,
    )
    return evaluation.paths[0].dropna().to_numpy(dtype="float64")


def _per_symbol_datasets(
    config: Config,
    repository: Repository,
    symbols: Sequence[str],
    start: datetime,
    end: datetime,
) -> dict[str, StrategyDataset]:
    """Build one :class:`StrategyDataset` per symbol (for the cross-symbol leave-one-out)."""
    datasets: dict[str, StrategyDataset] = {}
    for symbol in symbols:
        bars = repository.read_bars(symbol, start, end)
        if bars.empty:
            continue
        symbol_dataset = build_symbol_dataset(symbol, bars, config)
        if len(symbol_dataset) > 0:
            datasets[symbol] = _symbol_to_strategy_dataset(symbol_dataset)
    if len(datasets) < 2:
        raise PipelineError("cross-symbol validation needs >= 2 symbols with labelled events")
    return datasets


def _load_artifact(config: Config, registry: ModelRegistry) -> tuple[GatedEnsembleModel, str]:
    """Load the latest registered artifact under the configured model version."""
    registered = registry.latest(config.pipeline.registry_model_version)
    if registered is None:
        raise PipelineError(
            f"no artifact registered under {config.pipeline.registry_model_version!r}; "
            "run the P2A.6 final training first"
        )
    model = registered.model
    if not isinstance(model, GatedEnsembleModel):
        raise PipelineError(
            f"registered artifact is a {type(model).__name__}, expected GatedEnsembleModel"
        )
    return model, registered.card.model_id


def _pooled_to_strategy_dataset(pooled: PooledDataset) -> StrategyDataset:
    """Adapt a :class:`PooledDataset` to the model-agnostic :class:`StrategyDataset`."""
    return StrategyDataset(
        features=pooled.features,
        labels=pooled.labels,
        label_times=pooled.label_times,
        forward_returns=pooled.forward_returns,
        regime_features=pooled.regime_features,
    )


def _symbol_to_strategy_dataset(symbol_dataset: SymbolDataset) -> StrategyDataset:
    """Adapt one symbol's :class:`SymbolDataset` to a :class:`StrategyDataset`."""
    return StrategyDataset(
        features=symbol_dataset.features,
        labels=symbol_dataset.labels,
        label_times=symbol_dataset.label_times,
        forward_returns=symbol_dataset.forward_returns,
        regime_features=symbol_dataset.regime_features,
    )


def _empty_strategy_dataset() -> StrategyDataset:
    """A typed empty dataset (no labellable event) — the synthetic backtest skips these."""
    index = pd.DatetimeIndex([], name="event_time")
    return StrategyDataset(
        features=pd.DataFrame(index=index),
        labels=pd.Series(dtype="int64", index=index),
        label_times=pd.Series(dtype="datetime64[ns, Asia/Kolkata]", index=index),
        forward_returns=pd.Series(dtype="float64", index=index),
        regime_features=pd.DataFrame(index=index),
    )


def _log_battery(
    tracker: ExperimentTracker, run_name: str, report: RobustnessBatteryReport
) -> None:
    """Log each stress test as its own tracker run (the honest trial count for P2.9's DSR)."""
    tags = {
        "stage": "robustness",
        "model_id": report.model_id or "unregistered",
        "data_version": report.data_version,
        "label_version": report.label_version,
    }
    sens = report.parameter_sensitivity
    for variant, median in sens.median_by_variant.items():
        tracker.log_run(
            RunRecord(
                run_name=f"{run_name}-sensitivity-{variant}",
                params={"test": "parameter_sensitivity", "variant": variant},
                metrics={"median_path_sharpe": median},
                tags=tags,
            )
        )
    for level, median in report.noise_injection.median_by_level.items():
        tracker.log_run(
            RunRecord(
                run_name=f"{run_name}-noise-{level}",
                params={"test": "noise_injection", "noise_level": level},
                metrics={"median_path_sharpe": median},
                tags=tags,
            )
        )
    tracker.log_run(
        RunRecord(
            run_name=f"{run_name}-monte-carlo",
            params={"test": "monte_carlo_shuffle", "n_shuffles": report.monte_carlo.n_shuffles},
            metrics={
                "observed_max_drawdown": report.monte_carlo.observed_max_drawdown,
                "percentile_rank": report.monte_carlo.percentile_rank,
            },
            tags=tags,
        )
    )
    tracker.log_run(
        RunRecord(
            run_name=f"{run_name}-cross-symbol",
            params={"test": "cross_symbol"},
            metrics={
                "median_sharpe": report.cross_symbol.median,
                "fraction_positive": report.cross_symbol.fraction_positive,
                **{f"sharpe_{sym}": v for sym, v in report.cross_symbol.sharpe_by_symbol.items()},
            },
            tags=tags,
        )
    )
    tracker.log_run(
        RunRecord(
            run_name=f"{run_name}-synthetic",
            params={"test": "synthetic_data", "n_universes": report.synthetic.n_universes},
            metrics={
                "mean_median_sharpe": report.synthetic.mean_median,
                "fraction_positive": report.synthetic.fraction_positive,
            },
            tags=tags,
        )
    )
    tracker.log_run(
        RunRecord(
            run_name=f"{run_name}-reconciliation",
            params={"test": "two_engine_reconciliation"},
            metrics={
                "max_money_diff": report.reconciliation.max_money_diff,
                "reconciled": float(report.reconciliation.reconciled),
            },
            tags=tags,
        )
    )
