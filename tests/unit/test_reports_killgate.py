"""Tests for the seven-point kill-gate evaluator (P2.9, Deep Dive #2 "The kill-gate").

The gate is an AND of seven criteria with thresholds fixed in config (Inviolable Rule 1). These
pin each criterion's pass/fail boundary, the overall verdict, and the rendered decision block —
exhaustively, since this is the function that decides trade/don't-trade.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from quant.core.config import KillGateConfig
from quant.research.reports.killgate import (
    KillGateEvidence,
    KillGateVerdict,
    evaluate_kill_gate,
)


def _config(**over: Any) -> KillGateConfig:
    return KillGateConfig(**over)


def _evidence(**over: Any) -> KillGateEvidence:
    """A *passing* evidence bundle; override fields to fail a specific criterion."""
    base: dict[str, Any] = {
        "cpcv_median_path_sharpe": 1.5,
        "deflated_sharpe_ratio": 0.98,
        "pbo": 0.10,
        "fraction_negative_paths": 0.0,
        "worst_path_sharpe": 0.30,
        "profit_factor": 1.6,
        "trade_concentration": 0.2,
        "robustness_passed": True,
        "robustness_detail": "all green",
        "regime_mean_returns": {0: 0.001, 1: 0.002},
        "regime_observation_counts": {0: 50, 1: 60},
    }
    base.update(over)
    regimes: Mapping[int, float] = base.pop("regime_mean_returns")
    counts: Mapping[int, int] = base.pop("regime_observation_counts")
    return KillGateEvidence(regime_mean_returns=regimes, regime_observation_counts=counts, **base)


def test_all_criteria_pass_yields_pass() -> None:
    verdict = evaluate_kill_gate(_evidence(), _config())
    assert verdict.verdict == "PASS"
    assert verdict.passed
    assert verdict.failed_criteria == ()
    assert len(verdict.criteria) == 7
    assert all(c.mark == "PASS" for c in verdict.criteria)


@pytest.mark.parametrize(
    ("override", "failed_number"),
    [
        ({"cpcv_median_path_sharpe": 0.5}, 1),
        ({"deflated_sharpe_ratio": 0.5}, 2),
        ({"pbo": 0.6}, 3),
        ({"fraction_negative_paths": 0.5}, 4),
        ({"worst_path_sharpe": -2.0}, 4),
        ({"profit_factor": 0.9}, 5),
        ({"trade_concentration": 0.9}, 5),
        ({"robustness_passed": False, "robustness_detail": "knife_edge=True"}, 6),
        ({"regime_mean_returns": {0: -0.001, 1: 0.002}}, 7),
    ],
)
def test_each_criterion_can_fail(override: dict[str, Any], failed_number: int) -> None:
    verdict = evaluate_kill_gate(_evidence(**override), _config())
    assert verdict.verdict == "KILL"
    assert failed_number in {c.number for c in verdict.failed_criteria}


def test_criterion_1_boundary_is_strict() -> None:
    # Exactly at the threshold is NOT a pass (criterion 1 is strictly greater).
    at = evaluate_kill_gate(
        _evidence(cpcv_median_path_sharpe=1.0), _config(cpcv_median_sharpe_min=1.0)
    )
    assert not at.criteria[0].passed


def test_criterion_7_ignores_thin_regimes() -> None:
    # A loss-making regime with too few observations is ignored (below the observation floor).
    verdict = evaluate_kill_gate(
        _evidence(
            regime_mean_returns={0: 0.001, 1: -0.005},
            regime_observation_counts={0: 50, 1: 5},  # regime 1 too thin to judge
        ),
        _config(regime_min_observations=20),
    )
    assert verdict.criteria[6].passed
    assert "all 1 judged regimes" in verdict.criteria[6].detail


def test_criterion_7_fails_when_no_regime_reaches_the_floor() -> None:
    verdict = evaluate_kill_gate(
        _evidence(regime_observation_counts={0: 5, 1: 3}),
        _config(regime_min_observations=20),
    )
    assert not verdict.criteria[6].passed
    assert "no regime reached" in verdict.criteria[6].detail


def test_criterion_7_names_the_loss_making_regime() -> None:
    verdict = evaluate_kill_gate(
        _evidence(
            regime_mean_returns={0: 0.001, 1: -0.004},
            regime_observation_counts={0: 50, 1: 60},
        ),
        _config(),
    )
    crit = verdict.criteria[6]
    assert not crit.passed
    assert "loss-making regime(s) [1]" in crit.detail


def test_render_pass_and_fail() -> None:
    passed = evaluate_kill_gate(_evidence(), _config())
    pass_text = passed.render()
    assert "VERDICT: PASS" in pass_text
    assert "criteria failed" not in pass_text  # no failure count on a clean pass

    killed = evaluate_kill_gate(_evidence(pbo=0.9), _config())
    kill_text = killed.render()
    assert "VERDICT: KILL" in kill_text
    assert "1 criteria failed" in kill_text
    assert "[FAIL] (3)" in kill_text


def test_verdict_is_an_and() -> None:
    # Two independent failures both surface; the verdict is KILL while six criteria still pass.
    verdict = evaluate_kill_gate(_evidence(pbo=0.9, profit_factor=0.5), _config())
    assert {c.number for c in verdict.failed_criteria} == {3, 5}
    assert not verdict.passed


def test_verdict_dataclass_is_frozen() -> None:
    verdict = evaluate_kill_gate(_evidence(), _config())
    assert isinstance(verdict, KillGateVerdict)
    with pytest.raises(AttributeError):
        verdict.criteria = ()  # type: ignore[misc]
