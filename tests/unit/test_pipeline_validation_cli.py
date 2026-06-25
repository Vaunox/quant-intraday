"""Tests for the P2.9 validation-report CLI (``run_validation_report``).

The heavy orchestration is stubbed (it is tested in ``test_pipeline_validation.py``); here we pin
the CLI's own responsibility: argument/registry-dir wiring, tracker selection, writing the
rendered report to ``--output``, and the exit code (0 once the report generates — a KILL is a
successful report, not an error).
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

import quant.research.pipeline.validation_cli as cli
from quant.core.config import KillGateConfig
from quant.research.models.errors import ModelDependencyError
from quant.research.models.registry import InMemoryModelRegistry
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.validation_cli import default_tracker, main
from quant.research.reports.killgate import evaluate_kill_gate
from quant.research.reports.report import ValidationReport, WalkForwardSummary
from tests.unit.pipeline_fakes import REPO_CONFIG
from tests.unit.test_reports_killgate import _evidence

_ENV = {"QUANT_CONFIG_DIR": str(REPO_CONFIG)}


def _canned_report() -> ValidationReport:
    verdict = evaluate_kill_gate(_evidence(pbo=0.9), KillGateConfig())  # a KILL
    return ValidationReport(
        model_id="ensemble-regime-v1-0001",
        data_version="15min-2sym",
        feature_set_version="core-v1",
        label_version="tb-cusum",
        n_obs=357,
        n_trials=5,
        periods_per_year=2800.0,
        cpcv_num_paths=5,
        cpcv_median_sharpe=-3.3,
        cpcv_mean_sharpe=-3.0,
        cpcv_std_sharpe=1.2,
        cpcv_worst_sharpe=-5.0,
        cpcv_fraction_negative=1.0,
        deflated_sharpe_ratio=0.0,
        pbo=0.9,
        profit_factor=0.6,
        trade_concentration=0.5,
        walk_forward=WalkForwardSummary(
            net_pnl=-1234.5, final_equity=998765.5, max_drawdown_pct=0.02, n_fills=42
        ),
        robustness_passed=False,
        robustness_detail="knife_edge=True",
        regime_mean_returns={0: -0.001, 1: 0.0005},
        verdict=verdict,
    )


def _argv(*extra: str) -> list[str]:
    return ["--start", "2024-01-01", "--end", "2024-12-31", "--symbols", "AAA", "BBB", *extra]


def _stub(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_build(
        config: object,
        repository: object,
        symbols: Sequence[str],
        start: object,
        end: object,
        *,
        registry: object,
        tracker: object,
        run_name: str,
    ) -> ValidationReport:
        captured.update(symbols=list(symbols), tracker=tracker, run_name=run_name)
        return _canned_report()

    monkeypatch.setattr(cli, "build_validation_report", fake_build)
    return captured


def test_main_returns_zero_and_writes_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _stub(monkeypatch)
    roots: dict[str, Path] = {}

    def registry_factory(root: Path) -> InMemoryModelRegistry:
        roots["root"] = root
        return InMemoryModelRegistry()

    out = tmp_path / "verdict.txt"
    code = main(
        _argv("--tracker", "memory", "--output", str(out)),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=registry_factory,
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 0  # a KILL is still a successful report
    assert "VERDICT: KILL" in out.read_text(encoding="utf-8")
    assert captured["symbols"] == ["AAA", "BBB"]
    assert roots["root"] == Path("models/registry")  # defaulted from pipeline config


def test_main_without_output_still_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch)
    code = main(
        _argv("--tracker", "memory", "--registry-dir", "custom/reg"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=lambda root: InMemoryModelRegistry(),
        tracker_factory=lambda kind, experiment: InMemoryExperimentTracker(),
    )
    assert code == 0


def test_main_passes_tracker_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch)
    seen: dict[str, str] = {}

    def tracker_factory(kind: str, experiment: str) -> InMemoryExperimentTracker:
        seen.update(kind=kind, experiment=experiment)
        return InMemoryExperimentTracker()

    main(
        _argv("--tracker", "memory", "--experiment", "p2.9-exp"),
        environ=_ENV,
        repository_factory=lambda config, tier: object(),  # type: ignore[arg-type,return-value]
        registry_factory=lambda root: InMemoryModelRegistry(),
        tracker_factory=tracker_factory,
    )
    assert seen == {"kind": "memory", "experiment": "p2.9-exp"}


def test_default_tracker_memory_and_unknown() -> None:
    assert isinstance(default_tracker("memory", "exp"), InMemoryExperimentTracker)
    with pytest.raises(ValueError, match="unknown tracker"):
        default_tracker("bogus", "exp")


def test_default_tracker_mlflow_requires_install() -> None:
    with pytest.raises(ModelDependencyError):
        default_tracker("mlflow", "exp")
