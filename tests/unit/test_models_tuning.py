"""Tests for purged-CV hyperparameter tuning (P2.6).

The discipline that matters: tuning is scored under the *same* purged k-fold the model is
evaluated on (never leaky ordinary k-fold), the best configuration is the highest mean
held-out score, and every candidate is logged as a trial (the honest DSR trial count).
"""

import numpy as np
import pandas as pd
import pytest

from quant.research.models.errors import ModelTrainingError
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.models.tuning import HyperparameterTuner, default_param_grid
from tests.unit.models_fakes import learnable_dataset, model_config


def test_default_grid_runs_and_selects_the_best_configuration() -> None:
    features, labels, label_times = learnable_dataset()
    tracker = InMemoryExperimentTracker()
    result = HyperparameterTuner(model_config()).tune(
        features, labels, label_times, tracker=tracker
    )

    assert len(result.trials) == 4  # 2 num_leaves x 2 min_child_samples x 1 learning_rate
    # The winner is the trial with the highest mean purged-CV score.
    best = max(result.trials, key=lambda trial: trial.mean_score)
    assert result.best_score == pytest.approx(best.mean_score)
    assert dict(result.best_overrides) == dict(best.overrides)
    # best_config carries the winning overrides on top of the base config.
    assert result.best_config.num_leaves == best.overrides["num_leaves"]
    assert result.best_config.model_version == "test-v1"


def test_every_candidate_is_logged_as_a_tuning_trial() -> None:
    features, labels, label_times = learnable_dataset()
    tracker = InMemoryExperimentTracker()
    HyperparameterTuner(model_config()).tune(features, labels, label_times, tracker=tracker)
    assert len(tracker.runs) == 4
    assert all(run.tags["stage"] == "tuning" for run in tracker.runs)
    assert all("cv_mean_score" in run.metrics for run in tracker.runs)


def test_trials_are_scored_under_the_configured_purged_folds() -> None:
    features, labels, label_times = learnable_dataset()
    result = HyperparameterTuner(model_config(cv_folds=4)).tune(
        features, labels, label_times, tracker=InMemoryExperimentTracker()
    )
    # Every fold is scorable on this balanced dataset, so each trial has cv_folds scores.
    assert all(len(trial.fold_scores) == 4 for trial in result.trials)


def test_custom_grid_is_respected() -> None:
    features, labels, label_times = learnable_dataset()
    result = HyperparameterTuner(model_config()).tune(
        features,
        labels,
        label_times,
        tracker=InMemoryExperimentTracker(),
        grid={"num_leaves": [7, 15, 31]},
    )
    assert len(result.trials) == 3
    assert {trial.overrides["num_leaves"] for trial in result.trials} == {7, 15, 31}


def test_empty_grid_raises() -> None:
    features, labels, label_times = learnable_dataset()
    with pytest.raises(ModelTrainingError, match="empty"):
        HyperparameterTuner(model_config()).tune(
            features, labels, label_times, tracker=InMemoryExperimentTracker(), grid={}
        )


def test_invalid_grid_value_fails_loud() -> None:
    features, labels, label_times = learnable_dataset()
    with pytest.raises(ModelTrainingError, match="invalid hyperparameter override"):
        HyperparameterTuner(model_config()).tune(
            features,
            labels,
            label_times,
            tracker=InMemoryExperimentTracker(),
            grid={"num_leaves": [1]},  # violates num_leaves > 1
        )


def test_all_degenerate_folds_raise() -> None:
    features, _, label_times = learnable_dataset()
    single_class = pd.Series(np.ones(len(features), dtype="int64"), index=features.index)
    with pytest.raises(ModelTrainingError, match="no configuration could be scored"):
        HyperparameterTuner(model_config()).tune(
            features, single_class, label_times, tracker=InMemoryExperimentTracker()
        )


def test_default_param_grid_is_capacity_modest() -> None:
    grid = default_param_grid()
    assert set(grid) == {"num_leaves", "min_child_samples", "learning_rate"}
    assert max(grid["num_leaves"]) <= 31  # shallow / regularized (§4.2)
