"""Tests for the P2.9 validation-report orchestration (the model + validation engine wired up).

The end-to-end test drives the *real* stack (ensemble + regime gate, net-of-cost CPCV, DSR, PBO,
robustness battery, walk-forward) over a small two-symbol synthetic universe and asserts the
acceptance criterion — *"report generates end-to-end and emits the kill-gate verdict"* — and that
costs flip the weak gross edge into a KILL. The targeted tests pin the helper branches.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant.core.config import Config
from quant.research.models.registry import FileModelRegistry
from quant.research.models.tracking import InMemoryExperimentTracker
from quant.research.pipeline.final_run import train_final_model
from quant.research.pipeline.validation import (
    _cscv_partitions,
    _events_per_year,
    _representative_round_trip_cost,
    _walk_forward,
    build_validation_report,
)
from tests.unit.pipeline_fakes import FakeRepository, flat_bars, minute_bars, pipeline_config

IST = ZoneInfo("Asia/Kolkata")
START = datetime(2024, 1, 1, tzinfo=IST)
END = datetime(2024, 12, 31, tzinfo=IST)


def _fast_config() -> Config:
    config = pipeline_config()
    rob = config.robustness.model_copy(
        update={
            "cpcv_groups": 4,
            "cpcv_test_groups": 1,
            "cpcv_embargo_pct": 0.0,
            "noise_levels": (0.1,),
            "noise_repeats": 1,
            "monte_carlo_shuffles": 20,
            "synthetic_universes": 1,
            "synthetic_sessions": 8,
            "random_seed": 7,
        }
    )
    return config.model_copy(update={"robustness": rob})


def _repo() -> FakeRepository:
    return FakeRepository(
        {
            "AAA": minute_bars("AAA", sessions=40, minutes=120, seed=1, drift=0.00006),
            "BBB": minute_bars("BBB", sessions=40, minutes=120, seed=2, drift=-0.00004),
        }
    )


def _register(config: Config, repo: FakeRepository, root: Path) -> FileModelRegistry:
    registry = FileModelRegistry(root)
    train_final_model(
        config,
        repo,
        ["AAA", "BBB"],
        START,
        END,
        registry=registry,
        tracker=InMemoryExperimentTracker(),
    )
    return registry


def test_build_validation_report_end_to_end_kills_the_weak_candidate(tmp_path: Path) -> None:
    config = _fast_config()
    repo = _repo()
    registry = _register(config, repo, tmp_path / "registry")
    tracker = InMemoryExperimentTracker()

    report = build_validation_report(
        config, repo, ["AAA", "BBB"], START, END, registry=registry, tracker=tracker
    )

    # The report generated end-to-end and carries every piece of evidence (acceptance criterion).
    assert report.model_id == "ensemble-regime-v1-0001"
    assert report.n_obs > 0
    assert report.n_trials >= 2  # the candidate-config panel (DSR denominator)
    assert report.periods_per_year > 0
    assert 0.0 <= report.pbo <= 1.0
    assert 0.0 <= report.deflated_sharpe_ratio <= 1.0

    # A weak edge, judged net of costs, dies — the expected, honest outcome (Rule 7).
    assert report.verdict.verdict == "KILL"
    assert len(report.verdict.criteria) == 7
    assert 1 in {c.number for c in report.verdict.failed_criteria}  # net CPCV Sharpe < 1.0

    # The render is a complete decision document, and the run is logged (the audit trail).
    assert "SEVEN-POINT KILL-GATE" in report.render()
    kill_runs = [r for r in tracker.runs if r.tags.get("stage") == "kill_gate"]
    assert len(kill_runs) == 1
    assert kill_runs[0].tags["verdict"] == "KILL"


def test_events_per_year() -> None:
    # 1000 events over ~one year -> ~1000 events/year.
    per_year = _events_per_year(1000, datetime(2024, 1, 1), datetime(2025, 1, 1))
    assert per_year == pytest.approx(1000 * 365.25 / 366, rel=0.02)  # 2024 is a leap year


def test_cscv_partitions_is_even_and_bounded() -> None:
    assert _cscv_partitions(1000) == 16  # capped at the default
    assert _cscv_partitions(30) == 14  # 30 // 2 = 15 -> largest even <= 15
    assert _cscv_partitions(5) == 2  # floored at 2
    assert _cscv_partitions(0) == 2


def test_representative_round_trip_cost_falls_back_without_bars() -> None:
    config = _fast_config()
    # No bars for the symbol -> neutral large-cap fallback, still a sane positive fraction.
    fraction = _representative_round_trip_cost(config, FakeRepository({}), "MISSING", START, END)
    assert 0.0 < fraction < 0.05


def test_walk_forward_with_no_events_is_flat(tmp_path: Path) -> None:
    config = _fast_config()
    repo = FakeRepository({"FLAT": flat_bars("FLAT", sessions=4)})
    # Flat bars -> no events -> empty targets -> a flat walk-forward (no fills, no drawdown).
    summary = _walk_forward(config, object(), repo, "FLAT", START, END)  # type: ignore[arg-type]
    assert summary.n_fills == 0
    assert summary.max_drawdown_pct == 0.0
    assert summary.net_pnl == pytest.approx(0.0)


def test_walk_forward_with_no_bars_is_flat() -> None:
    config = _fast_config()
    # No bars at all -> an empty equity curve -> the zero-drawdown short-circuit.
    summary = _walk_forward(config, object(), FakeRepository({}), "MISSING", START, END)  # type: ignore[arg-type]
    assert summary.n_fills == 0
    assert summary.max_drawdown_pct == 0.0
