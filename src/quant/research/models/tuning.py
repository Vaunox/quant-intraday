"""Hyperparameter tuning under purged cross-validation (Deep Dive #2 §4.2).

*"Hyperparameter tuning must use purged CV. Tuning with ordinary k-fold leaks and overfits
the tuning itself — you'll pick hyperparameters that look great only because they memorized
leaked future data."* So the search reuses the exact same
:class:`~quant.research.validation.splits.PurgedKFold` the model is evaluated on: each
candidate configuration is scored by its **mean held-out** score across the purged folds,
and the best is the one that generalizes, not the one that fit the noise.

Every candidate is logged as a run through the
:class:`~quant.research.models.tracking.ExperimentTracker` — which is also the honest trial
count the Deflated Sharpe Ratio needs (P2.2): *every* configuration tried is a trial. The
grid is an explicit argument (research-defined, not a production constant), with a small,
capacity-modest :func:`default_param_grid` as the sensible starting point.
"""

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pydantic import ValidationError

from quant.core.config import ModelConfig
from quant.core.logging import get_logger
from quant.research.models.baseline import booster_proba, fit_booster, params_from_config
from quant.research.models.errors import ModelTrainingError
from quant.research.models.scoring import Scorer, roc_auc
from quant.research.models.tracking import ExperimentTracker, RunRecord
from quant.research.validation.splits import PurgedKFold

_logger = get_logger(__name__)

#: A search space: each configuration field maps to its candidate values.
ParamGrid = Mapping[str, Sequence[Any]]


def default_param_grid() -> dict[str, list[Any]]:
    """Return a small, capacity-modest default grid (§4.2: shallow, regularized).

    Sweeps the primary capacity/regularization knobs only — keeping the trial count (and so
    the DSR deflation) honest beats an exhaustive search that inflates it.
    """
    return {
        "num_leaves": [15, 31],
        "min_child_samples": [20, 50],
        "learning_rate": [0.05],
    }


@dataclass(frozen=True, slots=True)
class TuningTrial:
    """One evaluated configuration: its field overrides and purged-CV score."""

    overrides: Mapping[str, Any]
    mean_score: float
    fold_scores: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class TuningResult:
    """The search outcome: the best configuration and every trial (in grid order)."""

    best_config: ModelConfig
    best_overrides: Mapping[str, Any]
    best_score: float
    trials: tuple[TuningTrial, ...]


class HyperparameterTuner:
    """Selects model hyperparameters by mean purged-CV score (higher-is-better)."""

    def __init__(self, base_config: ModelConfig) -> None:
        """Build the tuner from the base configuration the grid overrides."""
        self._base = base_config

    def tune(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        label_times: pd.Series,
        *,
        tracker: ExperimentTracker,
        grid: ParamGrid | None = None,
        sample_weight: pd.Series | None = None,
        scorer: Scorer = roc_auc,
    ) -> TuningResult:
        """Score every grid configuration under purged CV and return the best.

        Args:
            features: Point-in-time feature matrix, indexed by event time.
            labels: Binary outcomes ``{0, 1}`` aligned to ``features``.
            label_times: The ``t0 -> t1`` Series driving the purge/embargo.
            tracker: Where each candidate run is logged (the honest trial count).
            grid: The search space; defaults to :func:`default_param_grid`.
            sample_weight: Optional per-event training weights (P2.4).
            scorer: Higher-is-better held-out score (default ROC AUC).

        Returns:
            A :class:`TuningResult` whose ``best_config`` is the base config updated with the
            winning overrides (re-validated, so a bad grid value fails loud).

        Raises:
            ModelTrainingError: If the grid is empty or no configuration could be scored (e.g.
                every fold was single-class).
        """
        combinations = _grid_combinations(default_param_grid() if grid is None else grid)
        if not combinations:
            raise ModelTrainingError("hyperparameter grid is empty")
        weight_array = None if sample_weight is None else sample_weight.to_numpy(dtype="float64")
        splitter = PurgedKFold(self._base.cv_folds, embargo_pct=self._base.cv_embargo_pct)

        trials: list[TuningTrial] = []
        for overrides in combinations:
            fold_scores = self._score_config(
                overrides, features, labels, label_times, weight_array, splitter, scorer
            )
            mean_score = float(np.mean(fold_scores)) if fold_scores else float("nan")
            trials.append(
                TuningTrial(
                    overrides=overrides, mean_score=mean_score, fold_scores=tuple(fold_scores)
                )
            )
            tracker.log_run(
                RunRecord(
                    run_name=f"tune-{_overrides_label(overrides)}",
                    params={**params_from_config(_config_for(self._base, overrides)), **overrides},
                    metrics={
                        "cv_mean_score": mean_score,
                        "cv_folds_scored": float(len(fold_scores)),
                    },
                    tags={"model_version": self._base.model_version, "stage": "tuning"},
                )
            )

        best = _best_trial(trials)
        _logger.info(
            "hyperparameter search complete",
            extra={
                "trials": len(trials),
                "best_score": best.mean_score,
                "best": dict(best.overrides),
            },
        )
        return TuningResult(
            best_config=_config_for(self._base, best.overrides),
            best_overrides=best.overrides,
            best_score=best.mean_score,
            trials=tuple(trials),
        )

    def _score_config(
        self,
        overrides: Mapping[str, Any],
        features: pd.DataFrame,
        labels: pd.Series,
        label_times: pd.Series,
        weight_array: np.ndarray | None,
        splitter: PurgedKFold,
        scorer: Scorer,
    ) -> list[float]:
        """Return the per-fold held-out scores of one configuration under purged CV."""
        config = _config_for(self._base, overrides)
        params = params_from_config(config)
        fold_scores: list[float] = []
        for fold in splitter.split(label_times):
            y_train = labels.iloc[fold.train]
            y_test = labels.iloc[fold.test].to_numpy(dtype="float64")
            if y_train.nunique() < 2 or np.unique(y_test).size < 2:
                continue  # a degenerate fold can't train or be ranked — skip, don't fake a score
            weight_train = None if weight_array is None else weight_array[fold.train]
            booster = fit_booster(
                features.iloc[fold.train],
                y_train,
                params,
                config.num_boost_round,
                sample_weight=weight_train,
            )
            fold_scores.append(scorer(y_test, booster_proba(booster, features.iloc[fold.test])))
        return fold_scores


def _config_for(base: ModelConfig, overrides: Mapping[str, Any]) -> ModelConfig:
    """Return ``base`` with ``overrides`` applied, re-validated (a bad grid value fails loud)."""
    try:
        return ModelConfig.model_validate({**base.model_dump(), **overrides})
    except ValidationError as exc:
        raise ModelTrainingError(
            f"invalid hyperparameter override {dict(overrides)}: {exc}"
        ) from exc


def _grid_combinations(grid: ParamGrid) -> list[dict[str, Any]]:
    """Expand a grid into the Cartesian product of ``{field: value}`` override dicts."""
    if not grid:
        return []
    keys = list(grid.keys())
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]


def _overrides_label(overrides: Mapping[str, Any]) -> str:
    """A compact, stable run-name suffix for one configuration."""
    return "_".join(f"{key}={overrides[key]}" for key in sorted(overrides))


def _best_trial(trials: list[TuningTrial]) -> TuningTrial:
    """Return the highest mean-score trial, ignoring unscored (NaN) configurations."""
    scored = [trial for trial in trials if not np.isnan(trial.mean_score)]
    if not scored:
        raise ModelTrainingError("no configuration could be scored (every fold was degenerate)")
    return max(scored, key=lambda trial: trial.mean_score)
