"""Tests for the cross-family ensemble (P2.7, Deep Dive #2 §4.1 Step 3).

The acceptance bar: the ensemble blends the three families (rank-averaging or stacking) under
**purged CV with OOF-fit combiner/calibrator** (no leakage), produces a **calibrated** combined
signal, logs the run with **version tags**, exposes the live :class:`~quant.core.interfaces.Model`
contract, and is **deterministic** for a fixed seed. The combiners are also tested as pure
functions on probability matrices, independent of any fitted base model.
"""

import numpy as np
import pandas as pd
import pytest

from quant.core.interfaces import Model
from quant.research.models.ensemble import (
    EnsembleResult,
    EnsembleTrainer,
    RankAverageCombiner,
    StackCombiner,
    build_ensemble,
)
from quant.research.models.errors import ModelTrainingError
from quant.research.models.estimators import (
    Estimator,
    LightGBMEstimator,
    LogisticEstimator,
    XGBoostEstimator,
)
from quant.research.models.tracking import InMemoryExperimentTracker
from tests.unit.models_fakes import learnable_dataset, model_config


def _estimators() -> list[Estimator]:
    cfg = model_config()
    return [
        LightGBMEstimator.from_config(cfg),
        XGBoostEstimator.from_config(cfg),
        LogisticEstimator(),
    ]


def _train(
    method: str = "rank_average", seed: int = 1, n: int = 480, **cfg_overrides: object
) -> tuple[EnsembleResult, InMemoryExperimentTracker, pd.DataFrame, pd.Series]:
    features, labels, label_times = learnable_dataset(n=n, seed=seed)
    tracker = InMemoryExperimentTracker()
    result = EnsembleTrainer(_estimators(), model_config(**cfg_overrides), method=method).train(
        features, labels, label_times, tracker=tracker
    )
    return result, tracker, features, labels


# --------------------------------------------------------------------------- #
# Combiners as pure functions
# --------------------------------------------------------------------------- #
def test_rank_average_is_the_mean_of_per_model_quantiles() -> None:
    oof = np.array([[0.1, 0.9], [0.2, 0.8], [0.3, 0.7]])
    combiner = RankAverageCombiner.fit(oof)
    # Top-ranked row in model 0 (0.3) and bottom in model 1 (0.7) → quantiles (1.0 + 0.333)/2.
    combined = combiner.combine(oof)
    assert combined.shape == (3,)
    assert combined[2] == pytest.approx((3 / 3 + 1 / 3) / 2)


def test_rank_average_neutralizes_scale_between_models() -> None:
    # Model 1's scores are tiny but identically ordered; ranks make the blend scale-free.
    oof = np.array([[0.10, 0.001], [0.50, 0.002], [0.90, 0.003]])
    combined = RankAverageCombiner.fit(oof).combine(oof)
    assert combined[0] < combined[1] < combined[2]  # monotone in the shared ordering


def test_rank_average_rejects_wrong_column_count() -> None:
    combiner = RankAverageCombiner.fit(np.array([[0.1, 0.2], [0.3, 0.4]]))
    with pytest.raises(ModelTrainingError, match="rank-average expects 2"):
        combiner.combine(np.array([[0.1], [0.2]]))


def test_stack_meta_learner_learns_to_weight_the_informative_model() -> None:
    rng = np.random.default_rng(0)
    truth = (rng.uniform(size=300) < 0.5).astype("float64")
    informative = np.where(truth == 1, 0.8, 0.2) + rng.normal(0, 0.05, 300)
    useless = rng.uniform(size=300)
    oof = np.clip(np.column_stack([informative, useless]), 0, 1)
    combiner = StackCombiner.fit(oof, truth, l2=0.01)
    combined = combiner.combine(oof)
    # The combined score must rank the informative signal (AUC well above chance).
    from quant.research.models.scoring import roc_auc

    assert roc_auc(truth, combined) > 0.9


def test_stack_rejects_wrong_column_count() -> None:
    truth = np.array([0.0, 1.0, 0.0, 1.0])
    combiner = StackCombiner.fit(np.array([[0.1, 0.2]] * 4), truth, l2=1.0)
    with pytest.raises(ModelTrainingError, match="stack expects 2"):
        combiner.combine(np.array([[0.1, 0.2, 0.3]]))


# --------------------------------------------------------------------------- #
# EnsembleTrainer (the deliverable)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["rank_average", "stack"])
def test_ensemble_learns_signal_under_purged_cv(method: str) -> None:
    result, _, _, _ = _train(method=method)
    assert result.metrics["oos_combined_auc"] > 0.8
    # Every member is scored OOS and attributable by name.
    assert {"oos_auc_lightgbm", "oos_auc_xgboost", "oos_auc_logistic"} <= set(result.metrics)


def test_every_observation_has_an_out_of_fold_combined_score() -> None:
    result, _, features, _ = _train()
    assert not result.oof_combined.isna().any()
    assert len(result.oof_combined) == len(features)
    for series in result.member_oof.values():
        assert not series.isna().any()


def test_combined_calibration_does_not_worsen_brier_vs_a_naive_constant() -> None:
    result, _, _, labels = _train()
    # The isotonic fit on the OOF combined score yields a proper, finite Brier.
    assert 0.0 <= result.metrics["oos_calibrated_brier"] <= 0.25 + 1e-9


def test_run_is_logged_with_method_members_and_version_tags() -> None:
    result, tracker, _, _ = _train(method="stack")
    assert len(tracker.runs) == 1
    run = tracker.last_run
    assert run is not None
    assert run.tags["model_version"] == "test-v1"
    assert run.tags["stage"] == "ensemble"
    assert run.tags["method"] == "stack"
    assert run.params["members"] == "lightgbm,xgboost,logistic"
    assert run.metrics == result.metrics


def test_extra_version_tags_propagate_to_the_run() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    tracker = InMemoryExperimentTracker()
    EnsembleTrainer(_estimators(), model_config()).train(
        features,
        labels,
        label_times,
        tracker=tracker,
        extra_tags={"data_version": "d1", "feature_set_version": "f1", "label_version": "l1"},
    )
    assert tracker.last_run is not None
    assert tracker.last_run.tags["data_version"] == "d1"
    assert tracker.last_run.tags["feature_set_version"] == "f1"
    assert tracker.last_run.tags["label_version"] == "l1"


def test_fitted_ensemble_implements_the_live_inference_contract() -> None:
    result, _, _, _ = _train()
    model = result.model
    assert isinstance(model, Model)
    strong = model.predict({"signal": 2.5, "noise": 0.0})
    weak = model.predict({"signal": -2.5, "noise": 0.0})
    assert 0.0 <= weak <= strong <= 1.0
    assert strong > weak


def test_predict_proba_batch_matches_single_row() -> None:
    result, _, features, _ = _train()
    head = features.head(4)
    batch = result.model.predict_proba(head)
    singles = [
        result.model.predict({str(c): float(v) for c, v in row.items()})
        for _, row in head.iterrows()
    ]
    assert batch == pytest.approx(singles)


def test_predict_rejects_missing_feature() -> None:
    result, _, _, _ = _train()
    with pytest.raises(ModelTrainingError, match="missing features"):
        result.model.predict({"signal": 1.0})


def test_training_is_deterministic_for_a_fixed_seed() -> None:
    first, _, _, _ = _train()
    second, _, _, _ = _train()
    assert first.metrics == pytest.approx(second.metrics)
    assert first.oof_combined.to_numpy() == pytest.approx(second.oof_combined.to_numpy())


def test_build_ensemble_round_trips_predictions() -> None:
    features, labels, _ = learnable_dataset(n=300)
    model = build_ensemble(_estimators(), features, labels, method="rank_average")
    proba = model.predict_proba(features)
    assert proba.shape == (len(features),)
    assert np.all((proba >= 0.0) & (proba <= 1.0))


def test_build_ensemble_rejects_no_estimators() -> None:
    features, labels, _ = learnable_dataset(n=50)
    with pytest.raises(ModelTrainingError, match="at least one estimator"):
        build_ensemble([], features, labels)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_trainer_rejects_duplicate_member_names() -> None:
    cfg = model_config()
    dupes: list[Estimator] = [
        LightGBMEstimator.from_config(cfg),
        LightGBMEstimator.from_config(cfg),
    ]
    with pytest.raises(ModelTrainingError, match="unique"):
        EnsembleTrainer(dupes, cfg)


def test_trainer_rejects_unknown_method() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    with pytest.raises(ModelTrainingError, match="unknown combination method"):
        EnsembleTrainer(_estimators(), model_config(), method="bogus").train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_trainer_rejects_non_binary_labels() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    labels = labels.replace(0, -1)
    with pytest.raises(ModelTrainingError, match="binary"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_trainer_rejects_misaligned_inputs() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    with pytest.raises(ModelTrainingError, match="share one index"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features,
            labels.reset_index(drop=True),
            label_times,
            tracker=InMemoryExperimentTracker(),
        )


def test_trainer_rejects_no_estimators() -> None:
    with pytest.raises(ModelTrainingError, match="at least one estimator"):
        EnsembleTrainer([], model_config())


def test_trainer_rejects_empty_features() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    with pytest.raises(ModelTrainingError, match="empty"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features.iloc[:0],
            labels.iloc[:0],
            label_times.iloc[:0],
            tracker=InMemoryExperimentTracker(),
        )


def test_trainer_rejects_length_mismatch() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    with pytest.raises(ModelTrainingError, match="length mismatch"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features, labels.iloc[:-1], label_times, tracker=InMemoryExperimentTracker()
        )


def test_trainer_rejects_misaligned_sample_weight() -> None:
    features, labels, label_times = learnable_dataset(n=300)
    weights = pd.Series(np.ones(len(features)))  # RangeIndex, not the features index
    with pytest.raises(ModelTrainingError, match="sample_weight"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features,
            labels,
            label_times,
            tracker=InMemoryExperimentTracker(),
            sample_weight=weights,
        )


def test_trainer_rejects_single_class_labels() -> None:
    features, _, label_times = learnable_dataset(n=300)
    labels = pd.Series(np.ones(len(features), dtype="int64"), index=features.index)
    with pytest.raises(ModelTrainingError, match="both classes"):
        EnsembleTrainer(_estimators(), model_config()).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_trainer_rejects_too_few_rows_for_folds() -> None:
    index = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-02 09:15", "2024-01-02 09:30", "2024-01-02 09:45"])
    )
    features = pd.DataFrame({"signal": [0.1, 0.2, 0.3], "noise": [0.0, 0.1, 0.2]}, index=index)
    labels = pd.Series([0, 1, 0], index=index)
    label_times = pd.Series(list(index), index=index)
    with pytest.raises(ModelTrainingError, match="cv_folds"):
        EnsembleTrainer(_estimators(), model_config(cv_folds=4)).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_trainer_rejects_single_class_training_fold() -> None:
    # Class 1 appears only in the final block, so the last fold trains on all-class-0 rows.
    features, _, label_times = learnable_dataset(n=600)
    labels = pd.Series(np.zeros(600, dtype="int64"), index=features.index)
    labels.iloc[-20:] = 1
    with pytest.raises(ModelTrainingError, match="single class"):
        EnsembleTrainer(_estimators(), model_config(cv_folds=4)).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )
