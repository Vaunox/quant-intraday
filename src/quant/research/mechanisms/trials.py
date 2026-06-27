"""Honest, cumulative trial-count wiring for the Deflated Sharpe Ratio (Part VI / P6.2).

*"You must honestly track your trial count — every backtest variant counts, even the ones you
discarded."* The original program violated this once: a **hard-coded ``N=5``** deflated to an
honest cumulative **``N=23``** once the live MLflow run count was used, and that re-deflation was
one of the universe-independent causes that turned a claimed +0.662 Sharpe into the honest +0.148
(``docs/FINDINGS.md`` §4.1 cause (b)). This module makes that mistake **structurally impossible**
for every Part-VI run: the DSR trial count is pulled **automatically** from a live, cumulative
source — never passed as a literal.

The source is a :class:`TrialCountSource` Protocol:

* :class:`TrackerTrialCountSource` — counts every :class:`~quant.research.models.tracking.RunRecord`
  logged to an in-memory tracker (the always-available default; what the tests assert against).
* :class:`MlflowTrialCountSource` — counts the cumulative runs across the configured mechanical-edge
  MLflow experiments. MLflow pins ``pandas<3``, so — exactly like the experiment tracker (P2.6) and
  ArcticDB (P1.3) — it is an *optional, operator-installed* backend confined behind a narrow
  interface and imported lazily in one place (:func:`create_mlflow_trial_count_source`), never a
  declared dependency. A faithful fake module stands in for tests, so the translation is fully
  unit-tested with no install.

:func:`deflated_sharpe_auto` is the **single DSR entry point** for the mechanisms layer: it reads
``N`` from the source and forwards to the existing
:func:`~quant.research.validation.metrics.deflated_sharpe_ratio_from_returns`. An adversarial test
(``tests/unit/test_mechanisms_trials.py``) asserts that **no caller in the mechanisms package ever
passes a literal ``N``** to the DSR functions — the hard-coded-N path is removed and forbidden at
the call site (P6.2 done-when).
"""

from collections.abc import Sequence
from typing import Any, Protocol, cast, runtime_checkable

from quant.core.logging import get_logger
from quant.research.mechanisms.errors import TrialCountError
from quant.research.models.errors import ModelDependencyError
from quant.research.models.tracking import InMemoryExperimentTracker, import_mlflow
from quant.research.validation.metrics import ReturnsLike, deflated_sharpe_ratio_from_returns

_logger = get_logger(__name__)


@runtime_checkable
class TrialCountSource(Protocol):
    """A live, cumulative source of the honest DSR trial count ``N``.

    ``N`` counts **every variant ever run, including discarded ones** — so the count only ever
    grows across a research program and the DSR can never be flattered by under-counting.
    """

    def cumulative_trial_count(self) -> int:
        """Return the cumulative number of trials run so far (>= 0)."""
        ...


class TrackerTrialCountSource:
    """A :class:`TrialCountSource` backed by an in-memory experiment tracker (the default).

    Each :class:`~quant.research.models.tracking.RunRecord` logged to the tracker is one trial, so
    the cumulative count is simply the number of logged runs. This is the always-available,
    no-install equivalent of the MLflow run count and what the harness uses in tests / local dev.
    """

    def __init__(self, tracker: InMemoryExperimentTracker) -> None:
        """Bind to the in-memory tracker whose runs are the trials."""
        self._tracker = tracker

    def cumulative_trial_count(self) -> int:
        """The number of runs logged to the tracker (the cumulative trial count)."""
        return len(self._tracker.runs)


class MlflowSearchModule(Protocol):
    """The subset of the top-level ``mlflow`` module the trial-count source calls.

    Mirrors the real module's shape so it satisfies this Protocol structurally (we cast to it in
    :func:`create_mlflow_trial_count_source`); a fake module stands in for tests.
    """

    def search_runs(self, experiment_names: Sequence[str], *, output_format: str) -> Sequence[Any]:
        """Return every run across ``experiment_names`` (one element per run)."""
        ...


class MlflowTrialCountSource:
    """A :class:`TrialCountSource` that counts cumulative runs across the configured experiments.

    Holds an injected ``mlflow``-like module (the real one via
    :func:`create_mlflow_trial_count_source`, a fake in tests), so the counting logic is fully
    unit-tested with no install — the same confinement pattern as
    :class:`~quant.research.models.tracking.MLflowExperimentTracker`.
    """

    def __init__(self, mlflow_module: MlflowSearchModule, experiment_names: Sequence[str]) -> None:
        """Bind to an opened ``mlflow``-like module and the experiments forming the cumulative N."""
        if not experiment_names:
            raise TrialCountError(
                "MlflowTrialCountSource needs at least one experiment name "
                "(config.mechanisms.experiment_names); got none"
            )
        self._mlflow = mlflow_module
        self._experiment_names = tuple(experiment_names)

    def cumulative_trial_count(self) -> int:
        """Count every run across the configured experiments (the honest cumulative N)."""
        runs = self._mlflow.search_runs(list(self._experiment_names), output_format="list")
        count = len(runs)
        _logger.info(
            "mlflow cumulative trial count",
            extra={"experiments": list(self._experiment_names), "n_trials": count},
        )
        return count


def create_mlflow_trial_count_source(experiment_names: Sequence[str]) -> MlflowTrialCountSource:
    """Build an :class:`MlflowTrialCountSource` — the single, lazy ``mlflow`` import site.

    Args:
        experiment_names: the mechanical-edge experiments whose cumulative run count is the DSR N
            (``config.mechanisms.experiment_names``).

    Raises:
        TrialCountError: If ``mlflow`` is not installed (it is optional; install it in a
            ``pandas<3`` environment, or use :class:`TrackerTrialCountSource`).
    """
    # ``mlflow`` is referenced only within research/models/ (Ground Rule 1 confinement); the lazy
    # import goes through that single seam (``import_mlflow``) rather than importing it here.
    try:
        mlflow_module = import_mlflow()
    except ModelDependencyError as exc:
        raise TrialCountError(
            "MLflow is not installed. It is an optional backend that pins pandas<3 (like "
            "ArcticDB); install it in a pandas<3 environment, e.g. `pip install mlflow`, or use "
            "TrackerTrialCountSource (the in-memory default)."
        ) from exc
    return MlflowTrialCountSource(cast(MlflowSearchModule, mlflow_module), experiment_names)


def deflated_sharpe_auto(
    returns: ReturnsLike,
    sharpe_variance: float,
    *,
    trial_source: TrialCountSource,
) -> float:
    """The DSR with the trial count pulled **automatically** from the live cumulative source.

    The **only** way the mechanisms layer computes a Deflated Sharpe Ratio: ``N`` comes from
    ``trial_source.cumulative_trial_count()``, never a literal (P6.2; the direct fix for
    ``FINDINGS.md`` §4.1 cause (b)). Forwards to the existing
    :func:`~quant.research.validation.metrics.deflated_sharpe_ratio_from_returns` with that count
    (floored at 1, since a single trial carries no multiple-testing inflation).

    Args:
        returns: the (path-concatenated) net return series the DSR is computed on.
        sharpe_variance: variance of the trials' Sharpes (the deflation benchmark's ``V``).
        trial_source: the live cumulative trial-count source.
    """
    n_trials = max(trial_source.cumulative_trial_count(), 1)
    return deflated_sharpe_ratio_from_returns(returns, sharpe_variance, n_trials=n_trials)
