"""Tests for the P2A.6 final-run CLI (``run_final_training``).

Drives :func:`main` against fakes (repository / registry / tracker injected): a clean run exits
0, a registry whose reload does not predict identically exits 1, and the tracker selector and
registry-dir resolution behave. No MLflow install, no Parquet, no network.
"""

from pathlib import Path

import numpy as np
import pytest

from quant.research.models.errors import ModelDependencyError
from quant.research.models.registry import InMemoryModelRegistry, RegisteredModel
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.cli import default_tracker, main
from tests.unit.pipeline_fakes import REPO_CONFIG, FakeRepository, minute_bars

# Real config dir, with scalar overrides that keep the run small + fast (list fields like
# return_horizons stay at their defaults; only the slow knobs are shrunk).
_FAST_ENV = {
    "QUANT_CONFIG_DIR": str(REPO_CONFIG),
    "QUANT__model__num_boost_round": "15",
    "QUANT__model__num_leaves": "7",
    "QUANT__model__min_child_samples": "5",
    "QUANT__model__cv_folds": "3",
    "QUANT__features__regime_vol_lookback": "20",
    "QUANT__labeling__cusum_threshold": "0.004",
    "QUANT__pipeline__n_regimes": "2",
    "QUANT__pipeline__pool_gap_days": "2",
}


def _repo() -> FakeRepository:
    return FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=40, minutes=120, seed=1, drift=0.00005),
            "BBB": minute_bars("BBB", sessions=40, minutes=120, seed=2, drift=-0.00003),
        }
    )


def _argv(*extra: str) -> list[str]:
    return ["--start", "2024-01-01", "--end", "2024-12-31", "--symbols", "AAA", "BBB", *extra]


def test_main_returns_zero_on_clean_run() -> None:
    captured: dict[str, Path] = {}

    def registry_factory(root: Path) -> InMemoryModelRegistry:
        captured["root"] = root
        return InMemoryModelRegistry()

    code = main(
        _argv("--tracker", "memory"),
        environ=_FAST_ENV,
        repository_factory=lambda config, tier: _repo(),
        registry_factory=registry_factory,
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 0
    # Registry dir defaulted from pipeline config (no --registry-dir given).
    assert captured["root"] == Path("models/registry")


def test_main_honors_registry_dir_override() -> None:
    captured: dict[str, Path] = {}

    def registry_factory(root: Path) -> InMemoryModelRegistry:
        captured["root"] = root
        return InMemoryModelRegistry()

    main(
        _argv("--tracker", "memory", "--registry-dir", "custom/reg"),
        environ=_FAST_ENV,
        repository_factory=lambda config, tier: _repo(),
        registry_factory=registry_factory,
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert captured["root"] == Path("custom/reg")


class _PerturbingRegistry(InMemoryModelRegistry):
    """A registry whose reloaded artifact predicts differently (simulates a bad save)."""

    def get(self, model_id: str) -> RegisteredModel:
        registered = super().get(model_id)
        return RegisteredModel(model=_FlippedModel(registered.model), card=registered.card)


class _FlippedModel:
    def __init__(self, base: object) -> None:
        self._base = base

    def predict_proba(self, features: object) -> np.ndarray:
        return 1.0 - np.asarray(self._base.predict_proba(features))  # type: ignore[attr-defined]


def test_main_returns_one_when_round_trip_fails() -> None:
    code = main(
        _argv("--tracker", "memory"),
        environ=_FAST_ENV,
        repository_factory=lambda config, tier: _repo(),
        registry_factory=lambda root: _PerturbingRegistry(),
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 1


def test_default_tracker_memory_is_in_memory() -> None:
    assert isinstance(default_tracker("memory", "exp"), InMemoryExperimentTracker)


def test_default_tracker_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown tracker"):
        default_tracker("bogus", "exp")


def test_default_tracker_mlflow_requires_install() -> None:
    # mlflow is not installed in the engine/CI env (it pins pandas<3); selecting it must fail
    # loudly rather than silently fall back to the in-memory tracker.
    with pytest.raises(ModelDependencyError):
        default_tracker("mlflow", "exp")
