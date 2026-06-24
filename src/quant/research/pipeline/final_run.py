"""The final registry-promotable training run (P2A.6).

Retroactively completes the P2.7 deferral: train the production stack — the cross-family
ensemble + the GMM regime gate — on the **real** pooled dataset (P2A.3), log the run to
persistent MLflow, and write the artifact + model card into the
:class:`~quant.research.models.registry.FileModelRegistry`, ready for P2.8/P2.9 to judge.

This module is *orchestration only*: it wires the already-merged P2.7 code (estimators,
:class:`~quant.research.models.ensemble.EnsembleTrainer`, the regime gate, the registry) to the
pooled real dataset (:mod:`~quant.research.pipeline.dataset`). It adds no model maths. The one
deliverable-specific composition — bundling the trained ensemble with its fitted gate — lives in
:class:`~quant.research.pipeline.model.GatedEnsembleModel`.

The regime gate is fit on the **full-sample** strategy returns (in-sample): the deliverable is
the fitted stack as it would deploy, and the honest out-of-sample judgement of whether that gate
earns its keep is P2.8/P2.9's job (the CPCV path distribution / kill-gate). Every step is logged;
the run finishes with a registry **round-trip check** — the reloaded artifact must predict
identically to the in-memory model — so a corrupt or non-deterministic save is caught here, not in
P2.8.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from quant.core.config import Config, ModelConfig
from quant.core.interfaces import Repository
from quant.core.logging import get_logger
from quant.research.models.ensemble import EnsembleModel, EnsembleResult, EnsembleTrainer
from quant.research.models.estimators import Estimator, cross_family_estimators
from quant.research.models.evaluation import probability_to_position
from quant.research.models.regime import RegimeGate, fit_regime_gate
from quant.research.models.registry import ModelCard, ModelRegistry
from quant.research.models.tracking import ExperimentTracker
from quant.research.pipeline.dataset import (
    REGIME_FEATURES,
    PooledDataset,
    build_pooled_dataset,
    data_version,
    label_version,
)
from quant.research.pipeline.model import GatedEnsembleModel

_logger = get_logger(__name__)

#: Round-trip tolerance: pickle of a deterministic model must reload bit-identically, so the
#: reloaded artifact's predictions must match the in-memory model's to within float noise.
_ROUNDTRIP_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class FinalRunResult:
    """The outcome of the final run: the registered card, metrics, and the round-trip check."""

    card: ModelCard
    metrics: dict[str, float]
    data_version: str
    feature_set_version: str
    label_version: str
    n_obs: int
    symbols: tuple[str, ...]
    regime_multipliers: tuple[float, ...]
    roundtrip_max_abs_diff: float
    ensemble_result: EnsembleResult = field(repr=False)

    @property
    def roundtrip_ok(self) -> bool:
        """Whether the reloaded registry artifact predicts identically to the in-memory model."""
        return self.roundtrip_max_abs_diff <= _ROUNDTRIP_TOLERANCE

    @property
    def active_regimes(self) -> int:
        """How many regimes the gate left switched on (a non-zero multiplier)."""
        return sum(1 for multiplier in self.regime_multipliers if multiplier > 0.0)


def train_final_model(
    config: Config,
    repository: Repository,
    symbols: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    registry: ModelRegistry,
    tracker: ExperimentTracker,
    run_name: str | None = None,
    verify_rows: int = 512,
) -> FinalRunResult:
    """Train, register, and verify the final ensemble + regime-gate artifact on real data.

    Args:
        config: System config (decision frequency, feature/label/model/pipeline params).
        repository: The store to read the backfilled bars from (Parquet archive, by default).
        symbols: The universe symbols to pool into the one cross-sectional model.
        start: Inclusive window start (tz-aware IST).
        end: Inclusive window end (tz-aware IST).
        registry: Where the artifact + card are persisted (``FileModelRegistry`` for the real run).
        tracker: Where the run is logged (persistent MLflow for the real run; in-memory in tests).
        run_name: Tracker/run name; defaults to the configured registry model version.
        verify_rows: How many rows to compare in the registry round-trip check.

    Returns:
        A :class:`FinalRunResult` with the registered :class:`ModelCard`, the purged-CV metrics,
        the gate's regime multipliers, and the round-trip diff.

    Raises:
        PipelineError: If no symbol produced any labeled events.
        ModelTrainingError: On a degenerate (single-class) purged fold, etc.
    """
    pooled = build_pooled_dataset(config, repository, symbols, start, end)
    interval = f"{config.market.decision_frequency_minutes}min"
    dversion = data_version(symbols, start, end, interval)
    lversion = label_version(config.labeling)
    version_tags = {
        # Override EnsembleTrainer's default model_version (the LightGBM member's config tag) with
        # the registry version, so the MLflow run and the registered artifact agree on identity.
        "model_version": config.pipeline.registry_model_version,
        "data_version": dversion,
        "feature_set_version": config.features.feature_set_version,
        "label_version": lversion,
        "n_symbols": str(len(pooled.symbols)),
        "n_obs": str(pooled.n_obs),
    }

    ensemble_result = _train_ensemble(config, pooled, tracker, run_name, version_tags)
    gate = _fit_gate(config, pooled, ensemble_result.model)
    gated = GatedEnsembleModel(
        ensemble=ensemble_result.model,
        regime_gate=gate,
        regime_feature_names=REGIME_FEATURES,
    )

    card = registry.register(
        gated,
        model_version=config.pipeline.registry_model_version,
        data_version=dversion,
        feature_set_version=config.features.feature_set_version,
        label_version=lversion,
        metrics=ensemble_result.metrics,
        params=_registry_params(config, pooled, gate),
        tags=version_tags,
    )

    diff = _roundtrip_max_abs_diff(gated, registry.get(card.model_id).model, pooled, verify_rows)
    result = FinalRunResult(
        card=card,
        metrics=dict(ensemble_result.metrics),
        data_version=dversion,
        feature_set_version=config.features.feature_set_version,
        label_version=lversion,
        n_obs=pooled.n_obs,
        symbols=pooled.symbols,
        regime_multipliers=gate.multipliers,
        roundtrip_max_abs_diff=diff,
        ensemble_result=ensemble_result,
    )
    _logger.info(
        "final run complete",
        extra={
            "model_id": card.model_id,
            "n_obs": result.n_obs,
            "symbols": list(result.symbols),
            "active_regimes": result.active_regimes,
            "roundtrip_max_abs_diff": diff,
            "roundtrip_ok": result.roundtrip_ok,
        },
    )
    return result


def _train_ensemble(
    config: Config,
    pooled: PooledDataset,
    tracker: ExperimentTracker,
    run_name: str | None,
    version_tags: Mapping[str, str],
) -> EnsembleResult:
    """Train the cross-family ensemble under purged CV, logging the run to ``tracker``."""
    trainer = EnsembleTrainer(
        _build_estimators(config.model), config.model, method=config.pipeline.ensemble_method
    )
    return trainer.train(
        pooled.features,
        pooled.labels,
        pooled.label_times,
        tracker=tracker,
        sample_weight=pooled.weights,
        run_name=run_name or config.pipeline.registry_model_version,
        extra_tags=version_tags,
    )


def _fit_gate(config: Config, pooled: PooledDataset, model: EnsembleModel) -> RegimeGate:
    """Fit the regime gate on the full-sample strategy returns (in-sample; P2.8 judges OOS)."""
    proba = model.predict_proba(pooled.features)
    strategy_returns = probability_to_position(proba) * pooled.forward_returns.to_numpy(
        dtype="float64"
    )
    gate = fit_regime_gate(
        pooled.regime_features,
        config.pipeline.n_regimes,
        returns=strategy_returns,
        random_seed=config.model.random_seed,
    )
    if all(multiplier == 0.0 for multiplier in gate.multipliers):
        _logger.warning(
            "regime gate switched every regime off — the signal has no in-sample edge in any "
            "regime; the artifact is still registered for P2.8 to judge out-of-sample",
            extra={"multipliers": list(gate.multipliers)},
        )
    return gate


def _build_estimators(config: ModelConfig) -> tuple[Estimator, ...]:
    """The §4.1 cross-family stack (shared with the P2.8 battery via the estimators module)."""
    return cross_family_estimators(config)


def _registry_params(config: Config, pooled: PooledDataset, gate: RegimeGate) -> dict[str, object]:
    """The reproducibility params recorded on the model card (alongside the version tags)."""
    return {
        "ensemble_method": config.pipeline.ensemble_method,
        "members": ",".join(estimator.name for estimator in _build_estimators(config.model)),
        "n_regimes": config.pipeline.n_regimes,
        "regime_multipliers": ",".join(str(m) for m in gate.multipliers),
        "pool_gap_days": config.pipeline.pool_gap_days,
        "decision_frequency_minutes": config.market.decision_frequency_minutes,
        "num_boost_round": config.model.num_boost_round,
        "cv_folds": config.model.cv_folds,
        "cv_embargo_pct": config.model.cv_embargo_pct,
        "random_seed": config.model.random_seed,
        "n_obs": pooled.n_obs,
        "symbols": ",".join(pooled.symbols),
    }


def _roundtrip_max_abs_diff(
    in_memory: GatedEnsembleModel, reloaded: object, pooled: PooledDataset, verify_rows: int
) -> float:
    """Max absolute prediction difference between the in-memory and reloaded artifacts.

    The registry pickles a deterministic model, so a faithful save round-trips to identical
    predictions; any non-zero diff signals a serialization bug. Compared over a bounded sample
    of rows for speed.
    """
    rows = pooled.features.iloc[:verify_rows]
    if rows.empty:
        return 0.0
    reference = in_memory.predict_proba(rows)
    # ``reloaded`` is typed object (the registry stores an opaque artifact); it is the same class.
    restored = reloaded.predict_proba(rows)  # type: ignore[attr-defined]
    return float(np.max(np.abs(np.asarray(restored, dtype="float64") - reference)))
