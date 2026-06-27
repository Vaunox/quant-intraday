"""Tests for the honest cumulative trial-count DSR wiring (Part VI / P6.2).

Covers the in-memory + confined-MLflow trial-count sources, ``deflated_sharpe_auto`` pulling N
from the live count, and — the direct fix for ``FINDINGS.md`` §4.1 cause (b) — an adversarial
AST guard asserting **no caller in the mechanisms package ever passes a literal N** to the DSR.
"""

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import quant.research.mechanisms as mechanisms_pkg
from quant.research.mechanisms.errors import TrialCountError
from quant.research.mechanisms.trials import (
    MlflowTrialCountSource,
    TrackerTrialCountSource,
    create_mlflow_trial_count_source,
    deflated_sharpe_auto,
)
from quant.research.models.tracking import InMemoryExperimentTracker, RunRecord

_RNG = np.random.default_rng(7)


def _tracker(n_runs: int) -> InMemoryExperimentTracker:
    tracker = InMemoryExperimentTracker()
    for i in range(n_runs):
        tracker.log_run(RunRecord(run_name=f"trial-{i}", params={}, metrics={}))
    return tracker


def test_tracker_source_counts_every_run() -> None:
    source = TrackerTrialCountSource(_tracker(5))
    assert source.cumulative_trial_count() == 5


class _FakeMlflow:
    """A faithful stand-in for the subset of ``mlflow`` the trial-count source calls."""

    def __init__(self, runs_by_experiment: dict[str, int]) -> None:
        self._runs = runs_by_experiment
        self.calls: list[Sequence[str]] = []

    def search_runs(self, experiment_names: Sequence[str], *, output_format: str) -> list[Any]:
        assert output_format == "list"
        self.calls.append(tuple(experiment_names))
        total = sum(self._runs.get(name, 0) for name in experiment_names)
        return [object() for _ in range(total)]


def test_mlflow_source_counts_cumulative_runs_across_experiments() -> None:
    fake = _FakeMlflow({"mechanical-edge": 12, "mechanical-edge-p7.1": 8})
    source = MlflowTrialCountSource(fake, ["mechanical-edge", "mechanical-edge-p7.1"])
    assert source.cumulative_trial_count() == 20
    assert fake.calls == [("mechanical-edge", "mechanical-edge-p7.1")]


def test_mlflow_source_requires_experiment_names() -> None:
    with pytest.raises(TrialCountError, match="at least one experiment"):
        MlflowTrialCountSource(_FakeMlflow({}), [])


def test_create_mlflow_source_raises_without_install(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mlflow":
            raise ImportError("no mlflow")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(TrialCountError, match="MLflow is not installed"):
        create_mlflow_trial_count_source(["mechanical-edge"])


def test_deflated_sharpe_auto_pulls_n_from_source() -> None:
    returns = 0.01 + 0.01 * _RNG.standard_normal(400)
    variance = 0.04
    dsr_few = deflated_sharpe_auto(
        returns, variance, trial_source=TrackerTrialCountSource(_tracker(2))
    )
    dsr_many = deflated_sharpe_auto(
        returns, variance, trial_source=TrackerTrialCountSource(_tracker(50))
    )
    # A larger live trial count raises the deflation benchmark, so the DSR cannot increase.
    assert 0.0 <= dsr_many <= dsr_few <= 1.0


def test_deflated_sharpe_auto_floors_trial_count_at_one() -> None:
    # An empty source (N=0) must not crash the DSR; it floors to a single trial (no deflation).
    returns = 0.01 + 0.01 * _RNG.standard_normal(200)
    dsr = deflated_sharpe_auto(returns, 0.04, trial_source=TrackerTrialCountSource(_tracker(0)))
    assert 0.0 <= dsr <= 1.0


# --- The P6.2 guarantee: no literal N anywhere in the mechanisms package ---------------------

#: DSR functions and the positional index of their ``n_trials`` argument.
_DSR_FUNCS: dict[str, int] = {
    "deflated_sharpe_ratio": 5,
    "deflated_sharpe_ratio_from_returns": 2,
    "expected_maximum_sharpe_ratio": 1,
}


def _mechanisms_sources() -> list[Path]:
    package_dir = Path(mechanisms_pkg.__file__).parent
    return sorted(package_dir.glob("*.py"))


def _literal_n_offenders(tree: ast.AST) -> list[str]:
    """Return descriptions of any DSR call passing an integer literal in the n_trials slot."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in _DSR_FUNCS:
            continue
        index = _DSR_FUNCS[name]
        candidates: list[ast.expr] = []
        if len(node.args) > index:
            candidates.append(node.args[index])
        candidates += [kw.value for kw in node.keywords if kw.arg == "n_trials"]
        for value in candidates:
            if isinstance(value, ast.Constant) and isinstance(value.value, int):
                offenders.append(f"{name}(... n_trials={value.value!r}) at line {node.lineno}")
    return offenders


def test_no_caller_passes_a_literal_trial_count() -> None:
    """No mechanism-layer caller hard-codes the DSR trial count (FINDINGS §4.1 cause (b))."""
    offenders: list[str] = []
    sources = _mechanisms_sources()
    assert sources, "expected to scan the mechanisms package sources"
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for offender in _literal_n_offenders(tree):
            offenders.append(f"{path.name}: {offender}")
    assert not offenders, "hard-coded DSR trial count(s) found:\n" + "\n".join(offenders)


def test_guard_detects_a_planted_literal_n() -> None:
    """The guard itself fires on an intentionally-leaky literal — proving it can fail."""
    planted = ast.parse("deflated_sharpe_ratio_from_returns(r, v, n_trials=5)")
    assert _literal_n_offenders(planted)
    planted_positional = ast.parse("deflated_sharpe_ratio(s, n, sk, ku, var, 23)")
    assert _literal_n_offenders(planted_positional)
