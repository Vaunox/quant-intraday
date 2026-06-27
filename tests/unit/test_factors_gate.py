"""Tests for the benchmark-relative factor kill-gate (P3X.8)."""

from dataclasses import replace

from quant.research.factors.gate import GateMetrics, evaluate_factor_gate

# The §4 thresholds (mirrors config/factor_default.yaml kill_gate).
_KILL_GATE = {
    "active_ir_min": 0.75,
    "dsr_min": 0.95,
    "pbo_max": 0.2,
    "max_fraction_negative_paths": 0.05,
    "min_active_path_ir": -0.3,
    "max_sector_weight_pct": 25.0,
    "max_single_factor_active_share": 0.6,
}


def _passing_metrics() -> GateMetrics:
    return GateMetrics(
        active_ir=0.90,
        dsr=0.97,
        fraction_negative=0.0,
        worst_path_ir=0.10,
        pbo=0.10,
        max_sector_weight=0.24,
        max_single_factor_share=0.45,
        robustness_passed=True,
    )


def test_all_criteria_pass() -> None:
    verdict = evaluate_factor_gate(_passing_metrics(), _KILL_GATE)
    assert verdict.passed
    assert "VERDICT: PASS" in verdict.render()


def test_subthreshold_ir_fails_criterion_1() -> None:
    metrics = replace(_passing_metrics(), active_ir=0.50)  # below 0.75
    verdict = evaluate_factor_gate(metrics, _KILL_GATE)
    assert not verdict.passed
    assert not verdict.results["1. active IR (annualised, net)"][0]


def test_uncomputed_metric_counts_as_not_passed() -> None:
    metrics = GateMetrics(
        active_ir=0.90, dsr=0.97, fraction_negative=0.0, worst_path_ir=0.10
    )  # pbo / sector / factor-share / robustness all unset
    verdict = evaluate_factor_gate(metrics, _KILL_GATE)
    assert not verdict.passed  # the gate never passes on an unmeasured criterion
    assert not verdict.results["3. probability of backtest overfitting"][0]
    assert not verdict.results["6. survives robustness battery"][0]
    assert not verdict.results["7a. max sector weight"][0]


def test_negative_path_fails_criterion_5() -> None:
    metrics = replace(_passing_metrics(), fraction_negative=0.10)
    verdict = evaluate_factor_gate(metrics, _KILL_GATE)
    assert not verdict.results["4a. fraction negative paths"][0]
    assert not verdict.results["5. every active path net-positive"][0]
