"""Tests for the non-directional StrategySpec layer (Part VI / P6.1) on synthetic data.

Proves a mechanism runs end-to-end through the **existing** CPCV + seven-point kill-gate with no
change to the validation engine, and that the gate is genuinely wired (it both PASSes a strong
synthetic edge and KILLs a negative one).
"""

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest

from quant.core.calendar import IST
from quant.core.config import KillGateConfig
from quant.research.mechanisms.errors import SpecError
from quant.research.mechanisms.spec import (
    MechanismEvaluation,
    SeriesStrategySpec,
    StrategySpec,
    evaluate_spec_under_cpcv,
    mechanism_kill_gate_evidence,
    spec_backtest_fn,
    validate_spec_timeline,
)
from quant.research.mechanisms.trials import TrackerTrialCountSource
from quant.research.models.tracking import InMemoryExperimentTracker, RunRecord
from quant.research.reports.killgate import evaluate_kill_gate
from quant.research.validation.cpcv import CombinatorialPurgedCV

_N = 24
_INDEX = pd.date_range("2020-01-31", periods=_N, freq="30D", tz=IST)
_LABEL_TIMES = pd.Series(_INDEX + pd.Timedelta(days=21), index=_INDEX, name="t1")


def _spec(values: npt.NDArray[np.float64], name: str = "synthetic") -> SeriesStrategySpec:
    return SeriesStrategySpec(
        name=name,
        times=_LABEL_TIMES,
        net_returns=pd.Series(values, index=_INDEX, name="net"),
    )


def _positive_returns() -> npt.NDArray[np.float64]:
    """A strong, low-variance positive net edge (every event a small win)."""
    return 0.02 + 0.002 * np.cos(np.arange(_N, dtype="float64"))


def _negative_returns() -> npt.NDArray[np.float64]:
    """A net-negative edge — should KILL on criterion 1."""
    return -0.02 + 0.002 * np.cos(np.arange(_N, dtype="float64"))


def _tracker_source(n_runs: int) -> TrackerTrialCountSource:
    tracker = InMemoryExperimentTracker()
    for i in range(n_runs):
        tracker.log_run(RunRecord(run_name=f"trial-{i}", params={}, metrics={}))
    return TrackerTrialCountSource(tracker)


def test_series_spec_rejects_misaligned_returns() -> None:
    with pytest.raises(SpecError, match="net_returns index must equal label_times index"):
        SeriesStrategySpec(
            name="bad",
            times=_LABEL_TIMES,
            net_returns=pd.Series([0.1, 0.2], index=_INDEX[:2]),
        )


def test_series_spec_is_a_strategy_spec() -> None:
    spec = _spec(_positive_returns())
    assert isinstance(spec, StrategySpec)  # runtime-checkable Protocol
    assert spec.label_times.index.equals(_INDEX)


def test_spec_backtest_fn_returns_test_event_returns() -> None:
    spec = _spec(_positive_returns())
    backtest = spec_backtest_fn(spec)
    test = np.array([2, 5, 7], dtype=np.intp)
    out = backtest(np.array([0, 1], dtype=np.intp), test)
    # The adapter returns exactly the spec's net returns at the test positions.
    assert out.index.equals(_INDEX[test])
    assert out.to_numpy() == pytest.approx(spec.net_returns.iloc[test].to_numpy())


def test_evaluate_spec_under_cpcv_reconstructs_positive_distribution() -> None:
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)  # phi = C(3,1) = 3 paths
    ev = evaluate_spec_under_cpcv(_spec(_positive_returns()), cpcv, periods_per_year=2.0)
    assert isinstance(ev, MechanismEvaluation)
    assert ev.distribution.num_paths == 3
    assert ev.annualised_median_sharpe > 0.0
    assert ev.fraction_negative == pytest.approx(0.0)
    assert ev.representative_path.size == _N  # one path tiles the whole timeline once
    assert ev.dedup_tstat > 0.0


def test_dsr_uses_live_cumulative_trial_count() -> None:
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(_spec(_positive_returns()), cpcv, periods_per_year=2.0)
    # More trials => a higher deflation benchmark => a DSR no larger than with fewer trials.
    dsr_few = ev.deflated_sharpe(_tracker_source(3))
    dsr_many = ev.deflated_sharpe(_tracker_source(40))
    assert 0.0 <= dsr_many <= dsr_few <= 1.0


def test_end_to_end_pass_through_unchanged_kill_gate() -> None:
    """A strong synthetic mechanism clears all seven criteria via the existing kill-gate."""
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(_spec(_positive_returns()), cpcv, periods_per_year=2.0)
    evidence = mechanism_kill_gate_evidence(
        ev,
        trial_source=_tracker_source(3),
        pbo=0.0,
        robustness_passed=True,
        robustness_detail="synthetic: all flags green",
        regime_labels=np.zeros(_N, dtype=np.intp),  # one regime, > the 20-obs floor
        n_regimes=1,
    )
    verdict = evaluate_kill_gate(evidence, KillGateConfig())
    assert verdict.passed, verdict.render()
    assert verdict.verdict == "PASS"


def test_end_to_end_kill_on_negative_edge() -> None:
    """A net-negative mechanism is KILLed on criterion 1 — the gate is not rigged."""
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(_spec(_negative_returns()), cpcv, periods_per_year=2.0)
    evidence = mechanism_kill_gate_evidence(
        ev,
        trial_source=_tracker_source(3),
        pbo=0.0,
        robustness_passed=True,
        robustness_detail="synthetic",
        regime_labels=np.zeros(_N, dtype=np.intp),
        n_regimes=1,
    )
    verdict = evaluate_kill_gate(evidence, KillGateConfig())
    assert not verdict.passed
    assert 1 in {c.number for c in verdict.failed_criteria}  # CPCV median path-Sharpe fails


def test_mechanism_evidence_rejects_misaligned_regimes() -> None:
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(_spec(_positive_returns()), cpcv, periods_per_year=2.0)
    with pytest.raises(SpecError, match="regime_labels length"):
        mechanism_kill_gate_evidence(
            ev,
            trial_source=_tracker_source(3),
            pbo=0.0,
            robustness_passed=True,
            robustness_detail="x",
            regime_labels=np.zeros(_N - 1, dtype=np.intp),
            n_regimes=1,
        )


def test_evidence_without_regimes_cannot_pass_criterion_7() -> None:
    """Omitting the regime breakdown leaves criterion 7 unjudged — the honest default is FAIL."""
    cpcv = CombinatorialPurgedCV(4, 2, embargo_pct=0.0)
    ev = evaluate_spec_under_cpcv(_spec(_positive_returns()), cpcv, periods_per_year=2.0)
    evidence = mechanism_kill_gate_evidence(
        ev,
        trial_source=_tracker_source(3),
        pbo=0.0,
        robustness_passed=True,
        robustness_detail="x",
    )
    verdict = evaluate_kill_gate(evidence, KillGateConfig())
    assert 7 in {c.number for c in verdict.failed_criteria}


def test_validate_spec_timeline_rejects_too_few_events() -> None:
    spec = _spec(_positive_returns())
    validate_spec_timeline(spec, min_groups=4)  # 24 events, 4 groups: fine
    with pytest.raises(Exception):  # noqa: B017 - SplitError from the shared primitive
        validate_spec_timeline(spec, min_groups=_N + 1)
