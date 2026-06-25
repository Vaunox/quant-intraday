"""Tests for the validation report bundle + its cost/concentration/regime statistics (P2.9)."""

import numpy as np
import pytest

from quant.core.config import KillGateConfig, load_config
from quant.research.reports.killgate import evaluate_kill_gate
from quant.research.reports.report import (
    ValidationReport,
    WalkForwardSummary,
    net_event_returns,
    profit_factor,
    regime_breakdown,
    round_trip_cost_fraction,
    trade_concentration,
)
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.slippage import DepthAwareSlippage
from tests.unit.test_reports_killgate import _evidence

REPO_CONFIG = "config"


def _models() -> tuple[IndianCostModel, DepthAwareSlippage]:
    config = load_config(env="dev", environ={"QUANT_CONFIG_DIR": REPO_CONFIG})
    return IndianCostModel(config.costs), DepthAwareSlippage(config.slippage)


def test_round_trip_cost_fraction_in_expected_band() -> None:
    cost, slippage = _models()
    fraction = round_trip_cost_fraction(
        cost, slippage, price=1500.0, quantity=100, liquidity=50000.0
    )
    # ~0.12-0.20% round trip for a liquid name (Deep Dive #2 §4b.6), plus slippage.
    assert 0.001 < fraction < 0.01


def test_net_event_returns_charges_cost_scaled_by_position() -> None:
    positions = np.array([1.0, -1.0, 0.5, 0.0])
    gross = np.array([0.01, -0.01, 0.02, 0.05])
    net = net_event_returns(positions, gross, round_trip_cost=0.002)
    # long: 0.01 - 0.002; short: (-1)(-0.01) - 0.002; half: 0.5*0.02 - 0.5*0.002; flat: 0 (no cost).
    assert net == pytest.approx([0.008, 0.008, 0.009, 0.0])


def test_profit_factor_cases() -> None:
    assert profit_factor(np.array([0.02, -0.01, 0.03, -0.02])) == pytest.approx(5 / 3)
    assert profit_factor(np.array([0.01, 0.02])) == float("inf")  # no losses
    assert profit_factor(np.array([-0.01, -0.02])) == 0.0  # no wins
    assert profit_factor(np.array([0.0, 0.0])) == 0.0  # nothing at all


def test_trade_concentration_cases() -> None:
    # One trade carries 0.04 of (0.04 + 0.01) = 0.8 of gross profit.
    assert trade_concentration(np.array([0.04, 0.01, -0.02])) == pytest.approx(0.8)
    assert trade_concentration(np.array([-0.01, -0.02])) == 0.0  # no gross profit


def test_regime_breakdown_omits_empty_regimes() -> None:
    regimes = np.array([0, 0, 2, 2, 2])
    net = np.array([0.01, -0.01, 0.02, 0.02, -0.04])
    means, counts = regime_breakdown(regimes, net, n_regimes=3)
    assert set(means) == {0, 2}  # regime 1 had no observations -> omitted
    assert counts == {0: 2, 2: 3}
    assert means[0] == pytest.approx(0.0)
    assert means[2] == pytest.approx(0.0)


def _report(**over: object) -> ValidationReport:
    config = KillGateConfig()
    verdict = evaluate_kill_gate(_evidence(), config)
    base: dict[str, object] = {
        "model_id": "ensemble-regime-v1-0001",
        "data_version": "15min-2sym",
        "feature_set_version": "core-v1",
        "label_version": "tb-cusum",
        "n_obs": 357,
        "n_trials": 5,
        "periods_per_year": 2800.0,
        "cpcv_num_paths": 5,
        "cpcv_median_sharpe": -3.3,
        "cpcv_mean_sharpe": -3.0,
        "cpcv_std_sharpe": 1.2,
        "cpcv_worst_sharpe": -5.0,
        "cpcv_fraction_negative": 1.0,
        "deflated_sharpe_ratio": 0.0,
        "pbo": 0.02,
        "profit_factor": 0.6,
        "trade_concentration": 0.5,
        "walk_forward": WalkForwardSummary(
            net_pnl=-1234.5, final_equity=998765.5, max_drawdown_pct=0.02, n_fills=42
        ),
        "robustness_passed": False,
        "robustness_detail": "knife_edge=True",
        "regime_mean_returns": {0: -0.001, 1: 0.0005},
        "verdict": verdict,
    }
    base.update(over)
    return ValidationReport(**base)  # type: ignore[arg-type]


def test_validation_report_render_contains_every_section() -> None:
    text = _report().render()
    for marker in (
        "VALIDATION REPORT",
        "ensemble-regime-v1-0001",
        "CPCV path-Sharpe distribution",
        "Deflated Sharpe Ratio",
        "PBO",
        "profit factor",
        "Walk-forward",
        "robustness battery",
        "regime mean net return",
        "SEVEN-POINT KILL-GATE",
    ):
        assert marker in text


def test_validation_report_passed_reflects_verdict() -> None:
    assert _report().passed is True  # _evidence() is a passing bundle
    config = KillGateConfig()
    killed = evaluate_kill_gate(_evidence(pbo=0.9), config)
    assert _report(verdict=killed).passed is False
