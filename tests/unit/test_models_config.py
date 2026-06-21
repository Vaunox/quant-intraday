"""Tests for the ModelConfig section (P2.6).

Confirms the baseline parameters load from the real ``default.yaml`` and that the
capacity-discipline constraints (§4.2) are enforced by the schema — a baseline can never
request an unbounded-depth tree or a single-leaf stump, and CV needs at least two folds.
"""

import pytest
from pydantic import ValidationError

from quant.core.config import ModelConfig, load_config


def test_model_config_loads_from_default_yaml() -> None:
    model = load_config().model
    assert model.objective == "binary"
    assert model.num_leaves == 31
    assert model.max_depth == 4
    assert model.cv_folds == 5
    assert model.model_version == "baseline-v1"


def _valid_kwargs() -> dict[str, object]:
    return {
        "objective": "binary",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "max_depth": 4,
        "min_child_samples": 50,
        "num_boost_round": 300,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l1": 0.0,
        "lambda_l2": 1.0,
        "min_gain_to_split": 0.0,
        "max_bin": 255,
        "cv_folds": 5,
        "cv_embargo_pct": 0.01,
        "permutation_repeats": 5,
        "random_seed": 7,
        "model_version": "baseline-v1",
    }


def test_capacity_discipline_constraints_are_enforced() -> None:
    # max_depth must stay positive (shallow trees, §4.2 — no unbounded-depth baseline).
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({**_valid_kwargs(), "max_depth": 0})
    # num_leaves must exceed 1 (a single leaf is not a model).
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({**_valid_kwargs(), "num_leaves": 1})
    # CV needs at least two folds.
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({**_valid_kwargs(), "cv_folds": 1})
    # The embargo fraction is a proper fraction in [0, 1).
    with pytest.raises(ValidationError):
        ModelConfig.model_validate({**_valid_kwargs(), "cv_embargo_pct": 1.0})
