"""Experiment tracking for model runs (Deep Dive #2 §4b.5 — "Experiment tracking: MLflow").

*"Log every trial — this is also how you get an honest trial count for the DSR."* Every
model run records its parameters, its purged-CV metrics, its permutation importances, and
the data/feature/label/model versions it was trained on (the §4 output contract).

MLflow is the named backend, but it **pins ``pandas<3``** (verified at resolve time), so —
exactly like ArcticDB in P1.3 — it is an *optional, operator-installed* backend confined
behind a narrow interface and imported lazily, never a declared dependency that would drag
the whole project's pandas down. Everything programs against the :class:`ExperimentTracker`
Protocol; the always-available :class:`InMemoryExperimentTracker` is the default (and what
the tests assert against), and :class:`MLflowExperimentTracker` is the thin translation to
MLflow's logging API, exercised against a faithful fake module with no ``mlflow`` install.
"""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from quant.core.logging import get_logger
from quant.research.models.errors import ModelDependencyError

_logger = get_logger(__name__)

#: Artifact filename for the permutation-importance map logged with each run.
IMPORTANCE_ARTIFACT = "permutation_importance.json"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One model run's complete, loggable record.

    ``params`` are the hyperparameters/CV settings; ``metrics`` the purged-CV scores;
    ``importances`` the averaged permutation (MDA) importances; ``tags`` the version stamps
    (data/feature/label/model) that make a run reproducible and registry-ready (P2.7).
    """

    run_name: str
    params: Mapping[str, Any]
    metrics: Mapping[str, float]
    importances: Mapping[str, float] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class ExperimentTracker(Protocol):
    """Where a model run is logged (in-memory by default, MLflow when installed)."""

    def log_run(self, record: RunRecord) -> None:
        """Persist a completed run's params, metrics, importances, and version tags."""
        ...


class InMemoryExperimentTracker:
    """The always-available default tracker: keeps every :class:`RunRecord` in memory.

    Used by the trainer in tests and for local development with no MLflow install. Also the
    natural feed for the honest DSR trial count (P2.2 ``TrialTracker``) — each recorded run
    is one trial.
    """

    def __init__(self) -> None:
        """Start with an empty run log."""
        self._runs: list[RunRecord] = []

    def log_run(self, record: RunRecord) -> None:
        """Append ``record`` to the in-memory log (and emit an INFO event)."""
        self._runs.append(record)
        _logger.info(
            "model run logged",
            extra={"run_name": record.run_name, "metrics": dict(record.metrics)},
        )

    @property
    def runs(self) -> list[RunRecord]:
        """All recorded runs, in log order."""
        return list(self._runs)

    @property
    def last_run(self) -> RunRecord | None:
        """The most recently logged run, or ``None`` if nothing has been logged."""
        return self._runs[-1] if self._runs else None


class MLflowModule(Protocol):
    """The subset of the top-level ``mlflow`` module this adapter calls.

    Method names/shapes mirror the real module so it satisfies this Protocol structurally
    (we cast to it in :func:`create_mlflow_tracker`); a fake module stands in for tests.
    """

    def set_experiment(self, experiment_name: str) -> Any:
        """Select (creating if needed) the active experiment."""
        ...

    def start_run(self, *, run_name: str | None = None) -> AbstractContextManager[Any]:
        """Open a run as a context manager (auto-ends, setting status, on exit)."""
        ...

    def set_tags(self, tags: Mapping[str, Any]) -> None:
        """Tag the active run."""
        ...

    def log_params(self, params: Mapping[str, Any]) -> None:
        """Log the active run's parameters."""
        ...

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        """Log the active run's metrics."""
        ...

    def log_dict(self, dictionary: Mapping[str, Any], artifact_file: str) -> None:
        """Log a dict (e.g. the importance map) as a run artifact."""
        ...


class MLflowExperimentTracker:
    """An :class:`ExperimentTracker` that logs each run to MLflow.

    Holds an injected ``mlflow``-like module (the real one via :func:`create_mlflow_tracker`,
    a fake in tests), so the translation logic is fully unit-tested with no install — the
    same confinement pattern as :class:`~quant.data.store.arctic.ArcticRepository`.
    """

    def __init__(self, mlflow_module: MLflowModule, *, experiment: str) -> None:
        """Bind the adapter to an opened ``mlflow`` module and select the experiment."""
        self._mlflow = mlflow_module
        self._mlflow.set_experiment(experiment)

    def log_run(self, record: RunRecord) -> None:
        """Open an MLflow run and log the record's params, metrics, importances, and tags."""
        with self._mlflow.start_run(run_name=record.run_name):
            if record.tags:
                self._mlflow.set_tags(dict(record.tags))
            if record.params:
                self._mlflow.log_params(dict(record.params))
            if record.metrics:
                self._mlflow.log_metrics(dict(record.metrics))
            # Importances go to a dict artifact, not metrics: feature names are not valid
            # MLflow metric keys, and the map is more useful retrieved whole.
            if record.importances:
                self._mlflow.log_dict(dict(record.importances), IMPORTANCE_ARTIFACT)
        _logger.info("mlflow run logged", extra={"run_name": record.run_name})


def import_mlflow() -> Any:
    """The single, lazy ``mlflow`` import site for the whole project (Ground Rule 1 confinement).

    MLflow is referenced **only** within ``research/models/`` (enforced by
    ``tests/unit/test_models_confinement.py``); every other layer that needs the cumulative run
    count or the tracker — including the Part-VI mechanical-edge harness — goes through this
    helper rather than importing ``mlflow`` itself, so the confinement stays a single seam.

    Raises:
        ModelDependencyError: If ``mlflow`` is not installed (it is optional; install it in a
            ``pandas<3`` environment, or use the in-memory defaults).
    """
    try:
        import mlflow
    except ImportError as exc:
        raise ModelDependencyError(
            "MLflow is not installed. It is an optional experiment-tracking backend that "
            "pins pandas<3 (like ArcticDB); install it in a pandas<3 environment, e.g. "
            "`pip install mlflow`, or use InMemoryExperimentTracker (the default)."
        ) from exc
    return mlflow


def create_mlflow_tracker(experiment: str) -> MLflowExperimentTracker:
    """Build an :class:`MLflowExperimentTracker` bound to the confined ``mlflow`` module.

    Args:
        experiment: The MLflow experiment name to log runs under.

    Returns:
        The adapter bound to the real ``mlflow`` module.

    Raises:
        ModelDependencyError: If ``mlflow`` is not installed (it is optional; install it in
            a ``pandas<3`` environment, or use :class:`InMemoryExperimentTracker`).
    """
    return MLflowExperimentTracker(  # pragma: no cover - reached only with mlflow installed
        cast(MLflowModule, import_mlflow()), experiment=experiment
    )
