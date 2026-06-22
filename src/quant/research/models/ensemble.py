"""The cross-family ensemble (Deep Dive #2 §4.1, Step 3 — "cross-family ensemble").

*"Combine boosting + a linear/logistic model … via **rank-averaging or stacking**. Diversity
across model families is more robust than one big tuned model."* This module blends the three
:mod:`~quant.research.models.estimators` families into one calibrated signal, under the same
P2.6 disciplines that make the baseline's verdict trustworthy:

* **Out-of-fold by construction.** The combiner (and the final calibrator) are fit on the
  pooled *out-of-fold* predictions of a :class:`~quant.research.validation.splits.PurgedKFold`
  — never in-sample — so a stacked meta-learner cannot leak, exactly as a stack must be built.
* **Two blend modes** (the deep dive offers either):
    * :class:`RankAverageCombiner` (default) — average each member's *rank* (its empirical
      quantile against that member's own OOF score distribution), neutralizing scale and
      miscalibration differences between families. Monotone per member, so it is well-defined
      for a single live row (its score → its quantile in the stored reference), not only for a
      batch — the point-in-time form of "rank averaging".
    * :class:`StackCombiner` — a logistic meta-learner over the members' OOF probabilities.
* **Calibrated output** (mandatory for conviction sizing, §4.2): an isotonic fit on the
  combined OOF score, reusing :mod:`~quant.research.models.calibration`.

The fitted :class:`EnsembleModel` implements the live :class:`~quant.core.interfaces.Model`
contract (``predict(features) -> calibrated probability``), so research and live share one
object — the same property the baseline guarantees. :func:`build_ensemble` is the lightweight
"fit on this slice" path the CPCV evaluator (:mod:`~quant.research.models.evaluation`) calls
per split; :class:`EnsembleTrainer` is the rigorous, tracked, registry-ready deliverable.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.config import ModelConfig
from quant.core.logging import get_logger
from quant.research.models.calibration import IsotonicCalibrator, fit_isotonic
from quant.research.models.errors import ModelTrainingError
from quant.research.models.estimators import (
    Estimator,
    FittedEstimator,
    FittedLogistic,
    LogisticEstimator,
)
from quant.research.models.scoring import brier_score, log_loss, roc_auc
from quant.research.models.tracking import ExperimentTracker, RunRecord
from quant.research.validation.splits import Fold, PurgedKFold

_logger = get_logger(__name__)

#: The supported blend modes (Deep Dive #2 §4.1 Step 3: "rank-averaging or stacking").
CombinationMethod = str  # Literal["rank_average", "stack"] at the call sites/config.


def fit_base_models(
    estimators: Sequence[Estimator],
    features: pd.DataFrame,
    labels: pd.Series,
    *,
    sample_weight: npt.NDArray[np.float64] | None = None,
) -> tuple[FittedEstimator, ...]:
    """Fit every base estimator on ``(features, labels)`` and return the fitted members."""
    return tuple(est.fit(features, labels, sample_weight=sample_weight) for est in estimators)


def base_proba_matrix(
    fitted: Sequence[FittedEstimator], features: pd.DataFrame
) -> npt.NDArray[np.float64]:
    """Stack members' ``predict_proba`` into an ``(n_rows, n_models)`` column matrix."""
    columns = [model.predict_proba(features) for model in fitted]
    return np.column_stack(columns) if columns else np.empty((features.shape[0], 0))


@runtime_checkable
class Combiner(Protocol):
    """Blends an ``(n_rows, n_models)`` probability matrix into one score per row."""

    def combine(self, proba_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return the combined score per row (a 1-D array of length ``n_rows``)."""
        ...


@dataclass(frozen=True, slots=True)
class RankAverageCombiner:
    """Average each member's empirical-quantile rank against its own reference distribution.

    For member ``m`` with sorted reference scores ``r_m`` (the OOF scores it produced during
    training), a new score ``s`` maps to ``rank = searchsorted(r_m, s, "right") / len(r_m)``
    ∈ ``[0, 1]`` — its quantile in that member's distribution. The combined score is the mean
    rank across members. Storing the reference (rather than ranking within the current batch)
    is what makes the blend point-in-time: a single live row ranks against history, not against
    its unknowable contemporaries.
    """

    references: tuple[npt.NDArray[np.float64], ...]  # per-member sorted OOF scores

    def combine(self, proba_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Mean of per-member empirical-quantile ranks of ``proba_matrix``'s columns."""
        if proba_matrix.shape[1] != len(self.references):
            raise ModelTrainingError(
                f"rank-average expects {len(self.references)} columns, got {proba_matrix.shape[1]}"
            )
        ranks = np.empty_like(proba_matrix, dtype="float64")
        for col, reference in enumerate(self.references):
            size = reference.shape[0] or 1
            ranks[:, col] = np.searchsorted(reference, proba_matrix[:, col], side="right") / size
        return np.asarray(ranks.mean(axis=1), dtype="float64")

    @classmethod
    def fit(cls, oof_matrix: npt.NDArray[np.float64]) -> "RankAverageCombiner":
        """Build references from each member's pooled OOF score column (sorted ascending)."""
        return cls(tuple(np.sort(oof_matrix[:, col]) for col in range(oof_matrix.shape[1])))


@dataclass(frozen=True, slots=True)
class StackCombiner:
    """A logistic meta-learner over the members' probabilities (the stacking blend).

    Trained on the members' **OOF** probabilities (never in-sample) so the meta-learner sees
    each base model's honest generalization, the discipline that keeps stacking from leaking.
    Reuses the hand-rolled :class:`~...estimators.LogisticEstimator`, so stacking adds no new
    dependency.
    """

    meta: FittedLogistic
    n_models: int

    def combine(self, proba_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Return the meta-learner's ``P(y=1)`` over the member-probability columns."""
        if proba_matrix.shape[1] != self.n_models:
            raise ModelTrainingError(
                f"stack expects {self.n_models} columns, got {proba_matrix.shape[1]}"
            )
        frame = pd.DataFrame(proba_matrix, columns=[f"m{i}" for i in range(self.n_models)])
        return self.meta.predict_proba(frame)

    @classmethod
    def fit(
        cls,
        oof_matrix: npt.NDArray[np.float64],
        truth: npt.NDArray[np.float64],
        *,
        l2: float,
        sample_weight: npt.NDArray[np.float64] | None = None,
    ) -> "StackCombiner":
        """Fit the logistic meta-learner on the OOF member probabilities."""
        n_models = oof_matrix.shape[1]
        frame = pd.DataFrame(oof_matrix, columns=[f"m{i}" for i in range(n_models)])
        meta = LogisticEstimator(l2=l2).fit(frame, pd.Series(truth), sample_weight=sample_weight)
        return cls(meta=meta, n_models=n_models)


def _fit_combiner(
    method: CombinationMethod,
    oof_matrix: npt.NDArray[np.float64],
    truth: npt.NDArray[np.float64],
    *,
    meta_l2: float,
    sample_weight: npt.NDArray[np.float64] | None,
) -> Combiner:
    """Fit the requested combiner on the OOF predictions (the single dispatch point)."""
    if method == "rank_average":
        return RankAverageCombiner.fit(oof_matrix)
    if method == "stack":
        return StackCombiner.fit(oof_matrix, truth, l2=meta_l2, sample_weight=sample_weight)
    raise ModelTrainingError(f"unknown combination method {method!r} (use 'rank_average'/'stack')")


@dataclass(frozen=True, slots=True)
class EnsembleModel:
    """A fitted cross-family ensemble exposing the live inference path.

    Holds the fitted members, the blend (:class:`Combiner`), and the isotonic calibrator.
    Implements :class:`~quant.core.interfaces.Model` (``predict(features) -> float``); the
    returned probability is always the **calibrated** combined score.
    """

    members: tuple[FittedEstimator, ...]
    member_names: tuple[str, ...]
    combiner: Combiner
    calibrator: IsotonicCalibrator
    feature_names: tuple[str, ...]

    def combined_raw(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the blended (pre-calibration) score per row."""
        return self.combiner.combine(base_proba_matrix(self.members, features))

    def predict_proba(self, features: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Return the calibrated ``P(y=1)`` per row (the conviction used for sizing)."""
        return self.calibrator.predict(self.combined_raw(features))

    def predict(self, features: Mapping[str, float]) -> float:
        """Return the calibrated ``P(y=1)`` for one point-in-time feature vector.

        Builds a one-row frame in trained feature order so column alignment cannot silently
        drift between training and live inference.

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


def build_ensemble(
    estimators: Sequence[Estimator],
    features: pd.DataFrame,
    labels: pd.Series,
    *,
    method: CombinationMethod = "rank_average",
    meta_l2: float = 1.0,
    sample_weight: npt.NDArray[np.float64] | None = None,
) -> EnsembleModel:
    """Fit members + combiner + calibrator on one slice (the per-split evaluation path).

    The combiner and calibrator are fit on the members' **in-sample** probabilities here;
    that is acceptable for CPCV evaluation because the held-out test set is still strictly
    out-of-sample and purged from this slice. For the leak-free *reported* metrics and the
    registry-bound model, use :meth:`EnsembleTrainer.train` (OOF-fit combiner/calibrator).
    """
    if not estimators:
        raise ModelTrainingError("an ensemble needs at least one estimator")
    members = fit_base_models(estimators, features, labels, sample_weight=sample_weight)
    matrix = base_proba_matrix(members, features)
    truth = labels.to_numpy(dtype="float64")
    combiner = _fit_combiner(method, matrix, truth, meta_l2=meta_l2, sample_weight=sample_weight)
    combined = combiner.combine(matrix)
    calibrator = fit_isotonic(combined, truth, sample_weight)
    return EnsembleModel(
        members=members,
        member_names=tuple(est.name for est in estimators),
        combiner=combiner,
        calibrator=calibrator,
        feature_names=tuple(str(c) for c in features.columns),
    )


@dataclass(frozen=True, slots=True)
class EnsembleResult:
    """The outcome of training the ensemble: the model, OOF predictions, and metrics."""

    model: EnsembleModel
    oof_combined: pd.Series  # pooled out-of-fold combined (pre-calibration) score
    oof_calibrated: pd.Series  # the same, after isotonic calibration
    member_oof: dict[str, pd.Series]  # each member's pooled OOF probability
    metrics: dict[str, float]  # purged-CV summary (combined + per-member OOS quality)
    run_record: RunRecord = field(repr=False)


class EnsembleTrainer:
    """Trains the cross-family ensemble under purged CV with OOF blending + calibration."""

    def __init__(
        self,
        estimators: Sequence[Estimator],
        config: ModelConfig,
        *,
        method: CombinationMethod = "rank_average",
        meta_l2: float = 1.0,
    ) -> None:
        """Build the trainer.

        Args:
            estimators: The base learners to blend (≥ 1; the §4.1 stack is LightGBM + XGBoost
                + logistic). Names must be unique so per-member OOF/metrics stay attributable.
            config: Shared model config (the purge folds, embargo, model version, seed).
            method: ``"rank_average"`` (default) or ``"stack"``.
            meta_l2: L2 penalty for the stacking meta-learner (ignored for rank averaging).

        Raises:
            ModelTrainingError: If no estimators are given or their names collide.
        """
        if not estimators:
            raise ModelTrainingError("an ensemble needs at least one estimator")
        names = [est.name for est in estimators]
        if len(set(names)) != len(names):
            raise ModelTrainingError(f"estimator names must be unique, got {names}")
        self._estimators = tuple(estimators)
        self._config = config
        self._method = method
        self._meta_l2 = meta_l2

    def train(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        label_times: pd.Series,
        *,
        tracker: ExperimentTracker,
        sample_weight: pd.Series | None = None,
        run_name: str | None = None,
        extra_tags: Mapping[str, str] | None = None,
    ) -> EnsembleResult:
        """Train and evaluate the ensemble under purged CV, logging the run to ``tracker``.

        Mirrors :class:`~quant.research.models.baseline.BaselineTrainer`: each fold fits every
        member on the purged train rows and predicts the held-out block, yielding pooled OOF
        member probabilities; the combiner and isotonic calibrator are fit on those OOF
        predictions; the deliverable members are then re-fit on **all** the data (calibrated
        via the OOF map). Every member name, the blend method, and the version tags are logged
        for the registry (P2.7) and the honest trial count (P2.2/P2.9).

        Args:
            features: Point-in-time feature matrix indexed by event time ``t0``.
            labels: Binary outcomes ``{0, 1}`` aligned to ``features``.
            label_times: The ``t0 -> t1`` Series (P2.3) driving the purge/embargo.
            tracker: Where the run is logged (in-memory by default; MLflow when installed).
            sample_weight: Optional per-event weights (P2.4) applied to fits + metrics.
            run_name: Tracker run name; defaults to the configured ``model_version``.
            extra_tags: Extra version stamps (data/feature/label versions) to record.

        Returns:
            An :class:`EnsembleResult`.

        Raises:
            ModelTrainingError: On a malformed/misaligned matrix, a non-binary label, or a
                degenerate (single-class) training fold.
        """
        _validate_training_inputs(
            features, labels, label_times, sample_weight, self._config.cv_folds
        )
        weight_array = None if sample_weight is None else sample_weight.to_numpy(dtype="float64")
        truth = labels.to_numpy(dtype="float64")
        n_models = len(self._estimators)

        oof = np.full((features.shape[0], n_models), np.nan, dtype="float64")
        splitter = PurgedKFold(self._config.cv_folds, embargo_pct=self._config.cv_embargo_pct)
        for fold in splitter.split(label_times):
            self._run_fold(fold, features, labels, weight_array, oof)

        # Fit the blend + calibration on the leak-free pooled OOF predictions.
        combiner = _fit_combiner(
            self._method, oof, truth, meta_l2=self._meta_l2, sample_weight=weight_array
        )
        combined = combiner.combine(oof)
        calibrator = fit_isotonic(combined, truth, weight_array)

        # The deliverable members are trained on ALL the data, calibrated via the OOF map.
        members = fit_base_models(self._estimators, features, labels, sample_weight=weight_array)
        model = EnsembleModel(
            members=members,
            member_names=tuple(est.name for est in self._estimators),
            combiner=combiner,
            calibrator=calibrator,
            feature_names=tuple(str(c) for c in features.columns),
        )

        metrics = self._summarize(truth, oof, combined, calibrator.predict(combined))
        record = RunRecord(
            run_name=run_name or self._config.model_version,
            params={
                "method": self._method,
                "members": ",".join(est.name for est in self._estimators),
                "meta_l2": self._meta_l2,
                "num_boost_round": self._config.num_boost_round,
                "cv_folds": self._config.cv_folds,
            },
            metrics=metrics,
            tags={
                "model_version": self._config.model_version,
                "stage": "ensemble",
                "method": self._method,
                **(extra_tags or {}),
            },
        )
        tracker.log_run(record)
        _logger.info(
            "ensemble trained",
            extra={"members": model.member_names, "method": self._method, "metrics": metrics},
        )
        index = features.index
        return EnsembleResult(
            model=model,
            oof_combined=pd.Series(combined, index=index, name="oof_combined"),
            oof_calibrated=pd.Series(calibrator.predict(combined), index=index, name="oof_cal"),
            member_oof={
                est.name: pd.Series(oof[:, col], index=index, name=est.name)
                for col, est in enumerate(self._estimators)
            },
            metrics=metrics,
            run_record=record,
        )

    def _run_fold(
        self,
        fold: Fold,
        features: pd.DataFrame,
        labels: pd.Series,
        weight_array: npt.NDArray[np.float64] | None,
        oof: npt.NDArray[np.float64],
    ) -> None:
        """Fit every member on the purged train rows; write their test predictions into ``oof``."""
        train, test = fold.train, fold.test
        y_train = labels.iloc[train]
        if y_train.nunique() < 2:
            raise ModelTrainingError(
                "a purged training fold has a single class — cannot train a classifier; "
                "use more events or fewer folds"
            )
        weight_train = None if weight_array is None else weight_array[train]
        members = fit_base_models(
            self._estimators, features.iloc[train], y_train, sample_weight=weight_train
        )
        for col, member in enumerate(members):
            oof[test, col] = member.predict_proba(features.iloc[test])

    def _summarize(
        self,
        truth: npt.NDArray[np.float64],
        oof: npt.NDArray[np.float64],
        combined: npt.NDArray[np.float64],
        combined_calibrated: npt.NDArray[np.float64],
    ) -> dict[str, float]:
        """Build the purged-CV summary: combined OOS quality + each member's OOS AUC."""
        metrics: dict[str, float] = {
            "n_obs": float(truth.shape[0]),
            "positive_rate": float(truth.mean()),
            "oos_combined_logloss": log_loss(truth, np.clip(combined, 0.0, 1.0)),
            "oos_calibrated_logloss": log_loss(truth, combined_calibrated),
            "oos_calibrated_brier": brier_score(truth, combined_calibrated),
        }
        if np.unique(truth).size == 2:
            metrics["oos_combined_auc"] = roc_auc(truth, combined)
            for col, est in enumerate(self._estimators):
                metrics[f"oos_auc_{est.name}"] = roc_auc(truth, oof[:, col])
        return metrics


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
