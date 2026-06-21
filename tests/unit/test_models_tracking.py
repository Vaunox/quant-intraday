"""Tests for experiment tracking: the in-memory default and the MLflow adapter (P2.6).

The MLflow adapter is exercised against a faithful fake module (no ``mlflow`` install), and
the missing-dependency path of :func:`create_mlflow_tracker` is asserted — it is reachable
in CI precisely because MLflow is an optional, operator-installed backend.
"""

import pytest

from quant.research.models.errors import ModelDependencyError
from quant.research.models.tracking import (
    IMPORTANCE_ARTIFACT,
    ExperimentTracker,
    InMemoryExperimentTracker,
    MLflowExperimentTracker,
    RunRecord,
    create_mlflow_tracker,
)
from tests.unit.models_fakes import FakeMLflowModule


def _record() -> RunRecord:
    return RunRecord(
        run_name="baseline-v1",
        params={"num_leaves": 15, "num_boost_round": 40},
        metrics={"oos_auc": 0.82, "oos_logloss": 0.51},
        importances={"signal": 0.30, "noise": 0.001},
        tags={"model_version": "baseline-v1", "objective": "binary"},
    )


def test_in_memory_tracker_records_runs() -> None:
    tracker = InMemoryExperimentTracker()
    assert tracker.last_run is None
    record = _record()
    tracker.log_run(record)
    assert tracker.runs == [record]
    assert tracker.last_run is record


def test_in_memory_tracker_satisfies_the_protocol() -> None:
    assert isinstance(InMemoryExperimentTracker(), ExperimentTracker)


def test_mlflow_adapter_logs_everything_inside_one_run() -> None:
    fake = FakeMLflowModule()
    tracker = MLflowExperimentTracker(fake, experiment="quant-baseline")
    assert fake.experiment == "quant-baseline"  # selected on construction

    tracker.log_run(_record())
    assert fake.started_runs == ["baseline-v1"]
    assert fake.params == {"num_leaves": 15, "num_boost_round": 40}
    assert fake.metrics == {"oos_auc": 0.82, "oos_logloss": 0.51}
    assert fake.tags == {"model_version": "baseline-v1", "objective": "binary"}
    # Importances go to a dict artifact (feature names are not valid metric keys), not metrics.
    assert fake.artifacts[IMPORTANCE_ARTIFACT] == {"signal": 0.30, "noise": 0.001}
    assert "signal" not in fake.metrics
    assert not fake.active  # the run was closed


def test_mlflow_adapter_satisfies_the_protocol() -> None:
    assert isinstance(
        MLflowExperimentTracker(FakeMLflowModule(), experiment="x"), ExperimentTracker
    )


def test_mlflow_adapter_skips_empty_sections() -> None:
    fake = FakeMLflowModule()
    MLflowExperimentTracker(fake, experiment="x").log_run(
        RunRecord(run_name="bare", params={}, metrics={})
    )
    assert fake.started_runs == ["bare"]
    assert fake.params == {} and fake.metrics == {}
    assert fake.artifacts == {}  # no importances -> no artifact


def test_create_mlflow_tracker_raises_when_not_installed() -> None:
    # MLflow is intentionally not a project dependency (it pins pandas<3); the lazy import
    # fails in CI, and we surface install guidance rather than an opaque ImportError.
    with pytest.raises(ModelDependencyError, match="MLflow is not installed"):
        create_mlflow_tracker("quant-baseline")
