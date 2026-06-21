"""Shared builders and fakes for the model-stack unit tests (P2.6).

A small synthetic dataset with a *known* learnable signal (so a trained booster's AUC,
importance ranking, and calibration are all checkable against ground truth) and a faithful
in-memory stand-in for the ``mlflow`` module — so the whole P2.6 surface, including the
MLflow adapter, runs with no ``mlflow`` install.

Not a ``test_*`` module, so pytest does not collect it; imported by the model tests.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant.core.config import ModelConfig

IST = ZoneInfo("Asia/Kolkata")


def model_config(**overrides: Any) -> ModelConfig:
    """A small, fast :class:`ModelConfig` for tests (low capacity, few boosting rounds)."""
    defaults: dict[str, Any] = {
        "objective": "binary",
        "learning_rate": 0.1,
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 20,
        "num_boost_round": 40,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "lambda_l1": 0.0,
        "lambda_l2": 1.0,
        "min_gain_to_split": 0.0,
        "max_bin": 255,
        "cv_folds": 4,
        "cv_embargo_pct": 0.0,
        "permutation_repeats": 3,
        "random_seed": 7,
        "model_version": "test-v1",
    }
    defaults.update(overrides)
    return ModelConfig.model_validate(defaults)


def learnable_dataset(
    n: int = 600,
    *,
    seed: int = 0,
    signal_strength: float = 3.0,
    label_span: int = 2,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return ``(features, labels, label_times)`` with a known signal and a noise feature.

    ``P(y=1) = sigmoid(signal_strength · signal)`` so ``signal`` genuinely predicts the label
    and ``noise`` does not — the ground truth for the importance and AUC assertions. Events
    are 15-minute spaced IST timestamps; each label window spans ``label_span`` bars, so
    adjacent windows overlap (the realistic case the purge handles).
    """
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 2, 9, 15, tzinfo=IST)
    index = pd.DatetimeIndex(
        [base + timedelta(minutes=15 * i) for i in range(n)], name="event_time"
    )
    signal = rng.normal(size=n)
    noise = rng.normal(size=n)
    probability = 1.0 / (1.0 + np.exp(-signal_strength * signal))
    labels = pd.Series((rng.uniform(size=n) < probability).astype("int64"), index=index, name="y")
    features = pd.DataFrame({"signal": signal, "noise": noise}, index=index)
    label_times = pd.Series(
        [index[min(i + label_span, n - 1)] for i in range(n)], index=index, name="t1"
    )
    return features, labels, label_times


@dataclass
class FakeMLflowModule:
    """In-memory stand-in for the top-level ``mlflow`` module (records every logged call).

    ``log_*``/``set_tags`` assert a run is active, proving the adapter logs *inside* an open
    run (the MLflow contract) — not before or after it.
    """

    experiment: str | None = None
    started_runs: list[str | None] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    active: bool = False

    def set_experiment(self, experiment_name: str) -> None:
        self.experiment = experiment_name

    @contextmanager
    def start_run(self, *, run_name: str | None = None) -> Iterator["FakeMLflowModule"]:
        self.started_runs.append(run_name)
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def set_tags(self, tags: Mapping[str, Any]) -> None:
        assert self.active, "set_tags called outside an active run"
        self.tags.update(tags)

    def log_params(self, params: Mapping[str, Any]) -> None:
        assert self.active, "log_params called outside an active run"
        self.params.update(params)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        assert self.active, "log_metrics called outside an active run"
        self.metrics.update(metrics)

    def log_dict(self, dictionary: Mapping[str, Any], artifact_file: str) -> None:
        assert self.active, "log_dict called outside an active run"
        self.artifacts[artifact_file] = dict(dictionary)
