"""The LightGBM baseline under proper discipline (Deep Dive #2 §4.1 Step 1, §4.2).

*"Baseline (do this first, always). A single LightGBM classifier on the primary-side label.
If a clean, well-labeled, cost-aware baseline isn't profitable in honest validation, no
deeper model will save it — that's your signal to iterate cheaply or kill the idea."*

This is that baseline, built to the four §4.2 disciplines so its verdict is trustworthy:

* **Evaluated only under purged CV** (Inviolable Rule 2). The booster is scored on the
  pooled *out-of-fold* predictions of a :class:`~quant.research.validation.splits.PurgedKFold`
  — every observation predicted by a model that never saw, and was purged around, it.
* **Permutation (MDA) importance, not MDI** (§4.2), computed within the CV on each held-out
  fold (:mod:`~quant.research.models.importance`) and averaged.
* **Calibrated probabilities** (§4.2, mandatory for conviction sizing): an isotonic fit on
  the leak-free pooled OOS predictions (:mod:`~quant.research.models.calibration`).
* **Modest capacity** — shallow, regularized trees from :class:`~quant.core.config.ModelConfig`.

The run (params, CV metrics, importances, version tags) is logged through an
:class:`~quant.research.models.tracking.ExperimentTracker`. The fitted
:class:`LightGBMBaseline` implements the live :class:`~quant.core.interfaces.Model` inference
contract (``predict(features) -> calibrated probability``), so research and live share one
object. The target is **binary** ``{0, 1}`` — the calibratable form the meta bet/no-bet label
(§3.4) and a binarized primary side both take.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.config import ModelConfig
from quant.core.logging import get_logger
from quant.research.models.calibration import IsotonicCalibrator, fit_isotonic
from quant.research.models.errors import ModelTrainingError
from quant.research.models.importance import permutation_importance
from quant.research.models.scoring import Scorer, accuracy, brier_score, log_loss, roc_auc
from quant.research.models.tracking import ExperimentTracker, RunRecord
from quant.research.validation.splits import PurgedKFold

_logger = get_logger(__name__)


def params_from_config(config: ModelConfig) -> dict[str, Any]:
    """Translate a :class:`ModelConfig` into LightGBM native-API parameters.

    Seeds (``seed``/``bagging_seed``/``feature_fraction_seed``) plus ``deterministic`` and
    ``force_row_wise`` make a fit reproducible (Ground Rule 7); ``verbosity=-1`` keeps the
    library quiet (our own structured logging is the audit trail).
    """
    seed = config.random_seed
    return {
        "objective": config.objective,
        "metric": "binary_logloss",
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "max_depth": config.max_depth,
        "min_child_samples": config.min_child_samples,
        "feature_fraction": config.feature_fraction,
        "bagging_fraction": config.bagging_fraction,
        "bagging_freq": config.bagging_freq,
        "lambda_l1": config.lambda_l1,
        "lambda_l2": config.lambda_l2,
        "min_gain_to_split": config.min_gain_to_split,
        "max_bin": config.max_bin,
        "seed": seed,
        "bagging_seed": seed,
        "feature_fraction_seed": seed,
        "deterministic": True,
        "force_row_wise": True,
        "verbosity": -1,
    }


def fit_booster(
    features: pd.DataFrame,
    labels: pd.Series,
    params: Mapping[str, Any],
    num_boost_round: int,
    *,
    sample_weight: npt.NDArray[np.float64] | None = None,
) -> lgb.Booster:
    """Train a LightGBM booster on ``(features, labels)`` via the native API.

    Shared by the trainer (final + per-fold fits) and the hyperparameter tuner, so LightGBM
    stays imported in this one module (the confinement discipline of P1.1/P1.3).
    """
    dataset = lgb.Dataset(features, label=labels.to_numpy(), weight=sample_weight)
    return lgb.train(dict(params), dataset, num_boost_round=num_boost_round)


def booster_proba(booster: lgb.Booster, features: pd.DataFrame) -> npt.NDArray[np.float64]:
    """Return the booster's ``P(y=1)`` per row as a float array (shared with the tuner)."""
    return np.asarray(booster.predict(features), dtype="float64").ravel()


@dataclass(frozen=True, slots=True)
class LightGBMBaseline:
    """A fitted baseline: a booster + isotonic calibrator, exposing the live inference path.

    Implements :class:`~quant.core.interfaces.Model` (``predict(features) -> float``) so the
    same trained object serves both research evaluation and live decisions. Probabilities are
    always the **calibrated** ones (raw available via :meth:`raw_proba` for diagnostics).
    """

    booster: lgb.Booster
    calibrator: IsotonicCalibrator
    feature_names: tuple[str, ...]

    def raw_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the booster's raw (uncalibrated) ``P(y=1)`` per row."""
        return booster_proba(self.booster, features[list(self.feature_names)])

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the calibrated ``P(y=1)`` per row (the conviction used for sizing)."""
        return self.calibrator.predict(self.raw_proba(features))

    def predict(self, features: Mapping[str, float]) -> float:
        """Return the calibrated ``P(y=1)`` for one point-in-time feature vector.

        Builds a one-row frame in the trained feature order, so column alignment can never
        silently drift between training and live inference.

        Raises:
            ModelTrainingError: If any trained feature is missing from ``features``.
        """
        missing = [name for name in self.feature_names if name not in features]
        if missing:
            raise ModelTrainingError(f"missing features for inference: {missing}")
        row = pd.DataFrame(
            [[features[name] for name in self.feature_names]], columns=list(self.feature_names)
        )
        return float(self.predict_proba(row)[0])


@dataclass(frozen=True, slots=True)
class BaselineResult:
    """The outcome of training the baseline: the model, its OOS predictions, and metrics."""

    model: LightGBMBaseline
    oos_raw: pd.Series  # pooled out-of-fold raw probabilities, indexed by event time
    oos_calibrated: pd.Series  # the same, after isotonic calibration
    fold_scores: tuple[float, ...]  # per-fold held-out scores (the scored folds)
    importances: dict[str, float]  # averaged permutation (MDA) importances
    metrics: dict[str, float]  # the purged-CV summary metrics (also logged)
    run_record: RunRecord = field(repr=False)  # what was sent to the tracker


class BaselineTrainer:
    """Trains the LightGBM baseline under purged CV with calibration and MDA importance."""

    def __init__(self, config: ModelConfig) -> None:
        """Build the trainer from the model configuration (capacity + CV + seed)."""
        self._config = config

    def train(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        label_times: pd.Series,
        *,
        tracker: ExperimentTracker,
        sample_weight: pd.Series | None = None,
        importance_scorer: Scorer = accuracy,
        fold_scorer: Scorer = roc_auc,
        run_name: str | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> BaselineResult:
        """Train and evaluate the baseline, logging the run to ``tracker``.

        Args:
            features: Point-in-time feature matrix, indexed by event time ``t0``.
            labels: Binary outcomes ``{0, 1}`` aligned to ``features`` (meta bet/no-bet, or a
                binarized primary side).
            label_times: The ``t0 -> t1`` Series (P2.3) driving the purge/embargo.
            tracker: Where the run is logged (in-memory by default; MLflow when installed).
            sample_weight: Optional per-event weights (e.g. average-uniqueness x time-decay,
                P2.4) applied to training, calibration, and the metrics.
            importance_scorer: Higher-is-better score for the MDA importance (default
                accuracy — the "A" in MDA).
            fold_scorer: Higher-is-better per-fold held-out score (default ROC AUC).
            run_name: Tracker run name; defaults to the configured ``model_version``.
            extra_tags: Extra version stamps (e.g. ``data_version``/``feature_set_version``/
                ``label_version``) to record for reproducibility.

        Returns:
            A :class:`BaselineResult`.

        Raises:
            ModelTrainingError: On a malformed matrix, misaligned inputs, a non-binary label,
                or a degenerate (single-class) training fold.
        """
        _validate_training_inputs(
            features, labels, label_times, sample_weight, self._config.cv_folds
        )
        params = params_from_config(self._config)
        feature_names = tuple(str(c) for c in features.columns)
        weight_array = None if sample_weight is None else sample_weight.to_numpy(dtype="float64")
        rng = np.random.default_rng(self._config.random_seed)

        oos_raw = np.full(features.shape[0], np.nan, dtype="float64")
        fold_scores: list[float] = []
        fold_importances: list[dict[str, float]] = []
        splitter = PurgedKFold(self._config.cv_folds, embargo_pct=self._config.cv_embargo_pct)
        for fold in splitter.split(label_times):
            self._run_fold(
                fold,
                features,
                labels,
                weight_array,
                params,
                rng,
                importance_scorer,
                fold_scorer,
                oos_raw,
                fold_scores,
                fold_importances,
            )

        truth: npt.NDArray[np.float64] = np.asarray(labels.to_numpy(), dtype="float64")
        oos_predictions = pd.Series(oos_raw, index=features.index, name="oos_raw")
        calibrator = fit_isotonic(oos_raw, truth, weight_array)
        calibrated_values = calibrator.predict(oos_raw)
        oos_calibrated = pd.Series(calibrated_values, index=features.index, name="oos_calibrated")

        # The deliverable model is trained on ALL the data, calibrated on the OOS predictions.
        final_booster = fit_booster(
            features, labels, params, self._config.num_boost_round, sample_weight=weight_array
        )
        model = LightGBMBaseline(final_booster, calibrator, feature_names)

        importances = _average_importances(fold_importances)
        metrics = _summarize(truth, oos_raw, calibrated_values, fold_scores)
        record = RunRecord(
            run_name=run_name or self._config.model_version,
            params={**params, "num_boost_round": self._config.num_boost_round},
            metrics=metrics,
            importances=importances,
            tags={
                "model_version": self._config.model_version,
                "objective": self._config.objective,
                **(extra_tags or {}),
            },
        )
        tracker.log_run(record)
        _logger.info(
            "baseline trained",
            extra={
                "n_obs": features.shape[0],
                "n_features": len(feature_names),
                "metrics": metrics,
            },
        )
        return BaselineResult(
            model=model,
            oos_raw=oos_predictions,
            oos_calibrated=oos_calibrated,
            fold_scores=tuple(fold_scores),
            importances=importances,
            metrics=metrics,
            run_record=record,
        )

    def _run_fold(
        self,
        fold: Any,
        features: pd.DataFrame,
        labels: pd.Series,
        weight_array: npt.NDArray[np.float64] | None,
        params: Mapping[str, Any],
        rng: np.random.Generator,
        importance_scorer: Scorer,
        fold_scorer: Scorer,
        oos_raw: npt.NDArray[np.float64],
        fold_scores: list[float],
        fold_importances: list[dict[str, float]],
    ) -> None:
        """Train on the purged train rows, predict + score the held-out test block in place."""
        x_train, y_train = features.iloc[fold.train], labels.iloc[fold.train]
        x_test, y_test = features.iloc[fold.test], labels.iloc[fold.test]
        if y_train.nunique() < 2:
            raise ModelTrainingError(
                "a purged training fold has a single class — cannot train a classifier; "
                "use more events or fewer folds"
            )
        weight_train = None if weight_array is None else weight_array[fold.train]
        booster = fit_booster(
            x_train, y_train, params, self._config.num_boost_round, sample_weight=weight_train
        )
        raw_test = booster_proba(booster, x_test)
        oos_raw[fold.test] = raw_test

        truth = y_test.to_numpy(dtype="float64")
        if np.unique(truth).size == 2:  # a single-class test block can't be ranked/AUC'd
            fold_scores.append(fold_scorer(truth, raw_test))
        fold_importances.append(
            permutation_importance(
                lambda frame: booster_proba(booster, frame),
                x_test,
                truth,
                n_repeats=self._config.permutation_repeats,
                rng=rng,
                scorer=importance_scorer,
            )
        )


def _validate_training_inputs(
    features: pd.DataFrame,
    labels: pd.Series,
    label_times: pd.Series,
    sample_weight: pd.Series | None,
    cv_folds: int,
) -> None:
    """Fail loud on any malformed/misaligned training input (Ground Rule 7)."""
    if features.empty or features.shape[1] == 0:
        raise ModelTrainingError("features matrix is empty")
    n = features.shape[0]
    if not (len(labels) == len(label_times) == n):
        raise ModelTrainingError(
            f"features/labels/label_times length mismatch: {n}/{len(labels)}/{len(label_times)}"
        )
    if not (features.index.equals(labels.index) and features.index.equals(label_times.index)):
        raise ModelTrainingError("features, labels, and label_times must share one index")
    if sample_weight is not None and not features.index.equals(sample_weight.index):
        raise ModelTrainingError("sample_weight must share the features index")
    truth = labels.to_numpy()
    if not np.all((truth == 0) | (truth == 1)):
        raise ModelTrainingError("labels must be binary {0, 1}")
    if np.unique(truth).size < 2:
        raise ModelTrainingError("labels must contain both classes")
    if n < cv_folds:
        raise ModelTrainingError(f"need at least cv_folds={cv_folds} events, got {n}")


def _average_importances(fold_importances: list[dict[str, float]]) -> dict[str, float]:
    """Average per-feature permutation importances across the folds that produced them."""
    if not fold_importances:
        return {}
    features = fold_importances[0].keys()
    return {name: float(np.mean([fold[name] for fold in fold_importances])) for name in features}


def _summarize(
    truth: npt.NDArray[np.float64],
    oos_raw: npt.NDArray[np.float64],
    oos_calibrated: npt.NDArray[np.float64],
    fold_scores: list[float],
) -> dict[str, float]:
    """Build the purged-CV summary metrics (raw vs calibrated OOS quality + fold spread)."""
    metrics: dict[str, float] = {
        "n_obs": float(truth.shape[0]),
        "positive_rate": float(truth.mean()),
        "oos_logloss": log_loss(truth, oos_raw),
        "oos_brier": brier_score(truth, oos_raw),
        "oos_calibrated_logloss": log_loss(truth, oos_calibrated),
        "oos_calibrated_brier": brier_score(truth, oos_calibrated),
    }
    if np.unique(truth).size == 2:
        metrics["oos_auc"] = roc_auc(truth, oos_raw)
    if fold_scores:
        scores = np.asarray(fold_scores, dtype="float64")
        metrics["cv_mean_score"] = float(scores.mean())
        metrics["cv_median_score"] = float(np.median(scores))
        metrics["cv_std_score"] = float(scores.std(ddof=1)) if scores.size > 1 else 0.0
        metrics["cv_folds_scored"] = float(scores.size)
    return metrics
