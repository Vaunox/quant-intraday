"""Tests for the cross-family base estimators (P2.7, Deep Dive #2 §4.1 Steps 2-3).

Each family (LightGBM, XGBoost, hand-rolled logistic) must satisfy the same tiny
:class:`~quant.research.models.estimators.Estimator` contract: fit on a known signal and learn
it, re-select columns by name at inference (no positional drift), and train **deterministically**
for a fixed seed (Ground Rule 7). The logistic member's standardization is point-in-time (train
stats reused at inference) and survives a constant column.
"""

import numpy as np
import pandas as pd
import pytest

from quant.research.models.errors import ModelTrainingError
from quant.research.models.estimators import (
    Estimator,
    FittedEstimator,
    LightGBMEstimator,
    LogisticEstimator,
    XGBoostEstimator,
    xgb_params_from_config,
)
from quant.research.models.scoring import roc_auc
from tests.unit.models_fakes import learnable_dataset, model_config


def _estimators() -> list[Estimator]:
    cfg = model_config()
    return [
        LightGBMEstimator.from_config(cfg),
        XGBoostEstimator.from_config(cfg),
        LogisticEstimator(),
    ]


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_every_family_learns_the_known_signal(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=500, seed=2)
    fitted = estimator.fit(features, labels)
    auc = roc_auc(labels.to_numpy(dtype="float64"), fitted.predict_proba(features))
    assert auc > 0.8  # all three families recover the planted signal in-sample


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_fitted_satisfies_the_contract_and_records_feature_order(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=300, seed=2)
    fitted = estimator.fit(features, labels)
    assert isinstance(fitted, FittedEstimator)
    assert fitted.feature_names == ("signal", "noise")


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_prediction_is_column_order_invariant(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=300, seed=2)
    fitted = estimator.fit(features, labels)
    reordered = features[["noise", "signal"]]  # swap column order at inference
    assert fitted.predict_proba(features) == pytest.approx(fitted.predict_proba(reordered))


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_training_is_deterministic_for_a_fixed_seed(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=300, seed=2)
    first = estimator.fit(features, labels).predict_proba(features)
    second = estimator.fit(features, labels).predict_proba(features)
    assert first == pytest.approx(second)


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_probabilities_are_in_the_unit_interval(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=300, seed=2)
    proba = estimator.fit(features, labels).predict_proba(features)
    assert np.all((proba >= 0.0) & (proba <= 1.0))


@pytest.mark.parametrize("estimator", _estimators(), ids=lambda e: e.name)
def test_sample_weights_are_accepted(estimator: Estimator) -> None:
    features, labels, _ = learnable_dataset(n=400, seed=2)
    weights = np.linspace(0.5, 1.5, len(features))
    fitted = estimator.fit(features, labels, sample_weight=weights)
    assert roc_auc(labels.to_numpy(dtype="float64"), fitted.predict_proba(features)) > 0.75


def test_xgb_params_map_the_shared_config_knobs() -> None:
    params = xgb_params_from_config(model_config(max_depth=3, lambda_l2=2.0, learning_rate=0.07))
    assert params["max_depth"] == 3  # depth-wise capacity knob (vs LightGBM num_leaves)
    assert params["reg_lambda"] == 2.0
    assert params["eta"] == 0.07
    assert params["nthread"] == 1 and params["seed"] == model_config().random_seed


def test_logistic_recovers_a_known_linear_boundary() -> None:
    # y = 1 iff signal > 0: a separable boundary the logistic slope must point along.
    rng = np.random.default_rng(0)
    signal = rng.normal(size=400)
    features = pd.DataFrame({"signal": signal, "noise": rng.normal(size=400)})
    labels = pd.Series((signal > 0).astype("int64"))
    fitted = LogisticEstimator().fit(features, labels)
    assert fitted.weights[0] > 0.0  # positive slope on the predictive feature
    assert abs(fitted.weights[1]) < fitted.weights[0]  # noise gets a smaller weight


def test_logistic_handles_a_constant_column() -> None:
    features = pd.DataFrame({"const": np.ones(50), "signal": np.linspace(-2, 2, 50)})
    labels = pd.Series((features["signal"] > 0).astype("int64"))
    fitted = LogisticEstimator().fit(features, labels)  # scale==0 guard prevents a divide-by-zero
    assert np.all(np.isfinite(fitted.predict_proba(features)))


def test_logistic_rejects_bad_hyperparameters() -> None:
    features, labels, _ = learnable_dataset(n=50, seed=0)
    for bad in (
        LogisticEstimator(max_iter=0),
        LogisticEstimator(learning_rate=0.0),
        LogisticEstimator(l2=-1.0),
    ):
        with pytest.raises(ModelTrainingError):
            bad.fit(features, labels)
