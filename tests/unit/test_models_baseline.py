"""Tests for the LightGBM baseline trainer (P2.6) — the acceptance criteria.

Asserts the four §4.2 disciplines on a dataset with a known signal: the booster is evaluated
**only under purged CV** (every observation predicted out-of-fold), importance is permutation
(MDA) with the true signal on top, the probabilities are **calibrated** (Brier no worse than
raw), the run is **logged** to the tracker, and the fitted model satisfies the live
:class:`~quant.core.interfaces.Model` inference contract.
"""

import numpy as np
import pandas as pd
import pytest

from quant.core.interfaces import Model
from quant.research.models.baseline import BaselineResult, BaselineTrainer
from quant.research.models.errors import ModelTrainingError
from quant.research.models.tracking import InMemoryExperimentTracker
from tests.unit.models_fakes import learnable_dataset, model_config


def _train(
    seed: int = 0, **config_overrides: object
) -> tuple[BaselineResult, InMemoryExperimentTracker, pd.DataFrame, pd.Series]:
    features, labels, label_times = learnable_dataset(seed=seed)
    tracker = InMemoryExperimentTracker()
    result = BaselineTrainer(model_config(**config_overrides)).train(
        features, labels, label_times, tracker=tracker
    )
    return result, tracker, features, labels


def test_baseline_learns_signal_under_purged_cv() -> None:
    result, _, _, _ = _train()
    # OOS AUC is computed purely on out-of-fold predictions (the honest, purged number).
    assert result.metrics["oos_auc"] > 0.8
    assert result.metrics["cv_folds_scored"] == 4.0


def test_every_observation_has_an_out_of_fold_prediction() -> None:
    result, _, features, _ = _train()
    # Purged k-fold partitions the test blocks, so every event is predicted exactly once OOS.
    assert not result.oos_raw.isna().any()
    assert len(result.oos_raw) == len(features)


def test_permutation_importance_ranks_the_true_signal_first() -> None:
    result, _, _, _ = _train()
    assert result.importances["signal"] > result.importances["noise"]
    assert result.importances["signal"] > 0.0


def test_calibration_does_not_worsen_brier() -> None:
    result, _, _, _ = _train()
    # Isotonic is fit on the pooled OOS predictions; the identity map is feasible, so the
    # calibrated Brier cannot exceed the raw Brier on that set.
    assert result.metrics["oos_calibrated_brier"] <= result.metrics["oos_brier"] + 1e-9


def test_run_is_logged_with_metrics_importances_and_version_tags() -> None:
    result, tracker, _, _ = _train()
    assert len(tracker.runs) == 1
    run = tracker.last_run
    assert run is not None
    assert run.run_name == "test-v1"
    assert run.tags["model_version"] == "test-v1"
    assert run.tags["objective"] == "binary"
    assert run.metrics == result.metrics
    assert run.importances == result.importances
    assert run.params["num_boost_round"] == 40  # the train arg is recorded alongside params


def test_extra_tags_propagate_to_the_run() -> None:
    features, labels, label_times = learnable_dataset()
    tracker = InMemoryExperimentTracker()
    BaselineTrainer(model_config()).train(
        features,
        labels,
        label_times,
        tracker=tracker,
        extra_tags={"feature_set_version": "core-v1", "label_version": "tb-v1"},
    )
    assert tracker.last_run is not None
    assert tracker.last_run.tags["feature_set_version"] == "core-v1"
    assert tracker.last_run.tags["label_version"] == "tb-v1"


def test_fitted_model_implements_the_live_inference_contract() -> None:
    result, _, _, _ = _train()
    model = result.model
    assert isinstance(model, Model)  # core.interfaces.Model (predict(features) -> float)
    strong = model.predict({"signal": 2.5, "noise": 0.0})
    weak = model.predict({"signal": -2.5, "noise": 0.0})
    assert 0.0 <= weak <= strong <= 1.0
    assert strong > 0.6 and weak < 0.4


def test_predict_proba_batch_matches_single_row() -> None:
    result, _, features, _ = _train()
    head = features.head(5)
    batch = result.model.predict_proba(head)
    singles = [
        result.model.predict({str(col): float(value) for col, value in row.items()})
        for _, row in head.iterrows()
    ]
    assert batch == pytest.approx(singles)


def test_predict_rejects_missing_feature() -> None:
    result, _, _, _ = _train()
    with pytest.raises(ModelTrainingError, match="missing features"):
        result.model.predict({"signal": 1.0})  # 'noise' absent


def test_training_is_deterministic_for_a_fixed_seed() -> None:
    first, _, _, _ = _train()
    second, _, _, _ = _train()
    assert first.metrics["oos_auc"] == pytest.approx(second.metrics["oos_auc"])
    assert first.importances == pytest.approx(second.importances)


def test_sample_weights_are_accepted() -> None:
    features, labels, label_times = learnable_dataset()
    weights = pd.Series(np.linspace(0.5, 1.5, len(features)), index=features.index)
    tracker = InMemoryExperimentTracker()
    result = BaselineTrainer(model_config()).train(
        features, labels, label_times, tracker=tracker, sample_weight=weights
    )
    assert result.metrics["oos_auc"] > 0.7  # still learns with weighted samples


def test_rejects_non_binary_labels() -> None:
    features, labels, label_times = learnable_dataset()
    labels = labels.replace(0, -1)  # {-1, 1} primary side, not the binary {0, 1} target
    with pytest.raises(ModelTrainingError, match="binary"):
        BaselineTrainer(model_config()).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_rejects_single_class_labels() -> None:
    features, labels, label_times = learnable_dataset()
    labels = pd.Series(np.ones(len(features), dtype="int64"), index=features.index)
    with pytest.raises(ModelTrainingError, match="both classes"):
        BaselineTrainer(model_config()).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_rejects_misaligned_inputs() -> None:
    features, labels, label_times = learnable_dataset()
    with pytest.raises(ModelTrainingError, match="share one index"):
        BaselineTrainer(model_config()).train(
            features,
            labels.reset_index(drop=True),
            label_times,
            tracker=InMemoryExperimentTracker(),
        )


def test_rejects_empty_features() -> None:
    features, labels, label_times = learnable_dataset()
    with pytest.raises(ModelTrainingError, match="empty"):
        BaselineTrainer(model_config()).train(
            features.iloc[:0],
            labels.iloc[:0],
            label_times.iloc[:0],
            tracker=InMemoryExperimentTracker(),
        )


def test_rejects_length_mismatch() -> None:
    features, labels, label_times = learnable_dataset()
    with pytest.raises(ModelTrainingError, match="length mismatch"):
        BaselineTrainer(model_config()).train(
            features, labels.iloc[:-1], label_times, tracker=InMemoryExperimentTracker()
        )


def test_rejects_misaligned_sample_weight() -> None:
    features, labels, label_times = learnable_dataset()
    weights = pd.Series(np.ones(len(features)))  # RangeIndex, not the features index
    with pytest.raises(ModelTrainingError, match="sample_weight"):
        BaselineTrainer(model_config()).train(
            features,
            labels,
            label_times,
            tracker=InMemoryExperimentTracker(),
            sample_weight=weights,
        )


def test_rejects_too_few_rows_for_folds() -> None:
    index = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-02 09:15", "2024-01-02 09:30", "2024-01-02 09:45"])
    )
    features = pd.DataFrame({"signal": [0.1, 0.2, 0.3]}, index=index)
    labels = pd.Series([0, 1, 0], index=index)
    label_times = pd.Series(list(index), index=index)
    with pytest.raises(ModelTrainingError, match="cv_folds"):
        BaselineTrainer(model_config(cv_folds=4)).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_single_class_training_fold_raises() -> None:
    # Class 1 appears only in the final block, so the last fold trains on all-class-0 rows.
    features, _, label_times = learnable_dataset(n=600)
    labels = pd.Series(np.zeros(600, dtype="int64"), index=features.index)
    labels.iloc[-20:] = 1
    with pytest.raises(ModelTrainingError, match="single class"):
        BaselineTrainer(model_config(cv_folds=4)).train(
            features, labels, label_times, tracker=InMemoryExperimentTracker()
        )


def test_average_importances_of_no_folds_is_empty() -> None:
    # Defensive guard: with no folds there is nothing to average (unreachable from train()).
    from quant.research.models.baseline import _average_importances

    assert _average_importances([]) == {}
