"""Tests for the P2.8 robustness-battery CLI (``run_robustness``).

Drives :func:`main` against fakes (repository / registry / tracker injected) with the heavy
battery stubbed — the battery itself is tested in ``test_pipeline_robustness.py``, so here we
pin only the CLI's own responsibility: argument/registry-dir wiring, tracker selection, and the
exit code (0 when the engines reconcile, 1 when they do not).
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

import quant.research.pipeline.robustness_cli as cli
from quant.research.models.errors import ModelDependencyError
from quant.research.models.registry import InMemoryModelRegistry
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.robustness import RobustnessBatteryReport
from quant.research.pipeline.robustness_cli import default_tracker, main
from quant.research.validation.reconcile import ReconciliationReport
from quant.research.validation.robustness import (
    CrossSymbolReport,
    MonteCarloShuffleReport,
    NoiseInjectionReport,
    ParameterSensitivityReport,
    SyntheticDataReport,
)
from tests.unit.pipeline_fakes import REPO_CONFIG

_ENV = {"QUANT_CONFIG_DIR": str(REPO_CONFIG)}


def _canned_report(*, reconciled: bool) -> RobustnessBatteryReport:
    diff = 1e-9 if reconciled else 5.0
    return RobustnessBatteryReport(
        model_id="ensemble-regime-v1-0001",
        data_version="d",
        label_version="l",
        feature_set_version="f",
        n_obs=100,
        symbols=("AAA", "BBB"),
        parameter_sensitivity=ParameterSensitivityReport(
            "baseline", {"baseline": 1.0, "v": 0.9}, 1.0
        ),
        noise_injection=NoiseInjectionReport(1.0, {0.1: 0.9}),
        monte_carlo=MonteCarloShuffleReport(0.1, np.array([0.05, 0.2]), 2),
        cross_symbol=CrossSymbolReport({"AAA": 0.5, "BBB": 0.4}),
        synthetic=SyntheticDataReport(np.array([0.0, 0.05]), 2, 0, 0.5),
        reconciliation=ReconciliationReport(10, 2, 2, 0.0, 0.0, 0.0, diff, 1e-6),
    )


def _argv(*extra: str) -> list[str]:
    return ["--start", "2024-01-01", "--end", "2024-12-31", "--symbols", "AAA", "BBB", *extra]


def _stub_battery(monkeypatch: pytest.MonkeyPatch, *, reconciled: bool) -> dict[str, object]:
    """Replace the heavy battery with a stub returning a canned report; capture its call."""
    captured: dict[str, object] = {}

    def fake_run(
        config: object,
        repository: object,
        symbols: Sequence[str],
        start: object,
        end: object,
        *,
        registry: object,
        tracker: object,
        run_name: str,
    ) -> RobustnessBatteryReport:
        captured.update(
            symbols=list(symbols), registry=registry, tracker=tracker, run_name=run_name
        )
        return _canned_report(reconciled=reconciled)

    monkeypatch.setattr(cli, "run_robustness_battery", fake_run)
    return captured


def test_main_returns_zero_when_engines_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_battery(monkeypatch, reconciled=True)
    roots: dict[str, Path] = {}

    def registry_factory(root: Path) -> InMemoryModelRegistry:
        roots["root"] = root
        return InMemoryModelRegistry()

    code = main(
        _argv("--tracker", "memory"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=registry_factory,
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 0
    assert captured["symbols"] == ["AAA", "BBB"]
    assert captured["run_name"] == "p2.8-robustness"
    assert roots["root"] == Path("models/registry")  # defaulted from pipeline config


def test_main_returns_one_when_engines_disagree(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_battery(monkeypatch, reconciled=False)
    code = main(
        _argv("--tracker", "memory"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=lambda root: InMemoryModelRegistry(),
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 1  # a reconciliation failure is an implementation bug -> non-zero exit


def test_main_honors_registry_dir_and_run_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_battery(monkeypatch, reconciled=True)
    roots: dict[str, Path] = {}

    def registry_factory(root: Path) -> InMemoryModelRegistry:
        roots["root"] = root
        return InMemoryModelRegistry()

    main(
        _argv("--tracker", "memory", "--registry-dir", "custom/reg", "--run-name", "smoke"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=registry_factory,
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert roots["root"] == Path("custom/reg")
    assert captured["run_name"] == "smoke"


def test_main_passes_tracker_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_battery(monkeypatch, reconciled=True)
    seen: dict[str, str] = {}

    def tracker_factory(kind: str, experiment: str) -> InMemoryExperimentTracker:
        seen["kind"] = kind
        seen["experiment"] = experiment
        return InMemoryExperimentTracker()

    main(
        _argv("--tracker", "memory", "--experiment", "my-exp"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=lambda root: InMemoryModelRegistry(),
        tracker_factory=tracker_factory,
    )
    assert seen == {"kind": "memory", "experiment": "my-exp"}
    assert isinstance(captured["tracker"], InMemoryExperimentTracker)


def test_default_tracker_memory_is_in_memory() -> None:
    assert isinstance(default_tracker("memory", "exp"), InMemoryExperimentTracker)


def test_default_tracker_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown tracker"):
        default_tracker("bogus", "exp")


def test_default_tracker_mlflow_requires_install() -> None:
    # mlflow is not installed in the engine/CI env (it pins pandas<3) -> fail loud, no silent
    # fall back to the in-memory tracker (a P2.9 trial-count correctness requirement).
    with pytest.raises(ModelDependencyError):
        default_tracker("mlflow", "exp")
