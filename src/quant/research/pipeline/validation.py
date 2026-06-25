"""Assemble the validation report + seven-point kill-gate verdict (P2.9 orchestration).

This is the layer that *runs* the model and the validation engine against the registered
artifact + real data to produce the evidence the kill-gate judges, then bundles it into a
:class:`~quant.research.reports.report.ValidationReport`. Like ``final_run`` and the robustness
orchestration, it wires already-merged code (the CPCV evaluator, DSR/PBO, the robustness battery,
the cost backtester) and adds no new statistics — only the assembly.

The one discipline that makes this honest (Deep Dive #2, "the kill-gate"): **every number is
net of costs and point-in-time.** Criterion 1 is *"CPCV median path-Sharpe after full Indian
costs and slippage"* — so the CPCV returns are netted by a representative round-trip cost
(:func:`~quant.research.reports.report.round_trip_cost_fraction`) charged once per triple-barrier
event, and annualised by the data-derived events-per-year. The gross ~0.04 the robustness battery
reports is *not* the kill-gate input; the net, annualised distribution is.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
import pandas as pd

from quant.core.config import Config
from quant.core.interfaces import Repository
from quant.core.logging import get_logger
from quant.research.models.estimators import Estimator, cross_family_estimators
from quant.research.models.evaluation import evaluate_ensemble_under_cpcv
from quant.research.models.registry import ModelRegistry
from quant.research.models.tracking import ExperimentTracker, RunRecord
from quant.research.pipeline.dataset import (
    PooledDataset,
    build_pooled_dataset,
    data_version,
    label_version,
    resample_bars,
)
from quant.research.pipeline.model import GatedEnsembleModel
from quant.research.pipeline.robustness import (
    RobustnessBatteryReport,
    _load_artifact,
    _sample_targets,
    run_robustness_battery,
)
from quant.research.reports.killgate import KillGateEvidence, KillGateVerdict, evaluate_kill_gate
from quant.research.reports.report import (
    ValidationReport,
    WalkForwardSummary,
    profit_factor,
    regime_breakdown,
    round_trip_cost_fraction,
    trade_concentration,
)
from quant.research.validation.backtest import create_backtester
from quant.research.validation.costs import IndianCostModel
from quant.research.validation.cpcv import CombinatorialPurgedCV, PathDistribution
from quant.research.validation.metrics import deflated_sharpe_ratio, return_moments
from quant.research.validation.pbo import DEFAULT_PARTITIONS, probability_of_backtest_overfitting
from quant.research.validation.slippage import DepthAwareSlippage
from quant.research.validation.trials import TrialTracker

_logger = get_logger(__name__)

#: Days per calendar year, for the events-per-year annualisation factor.
_DAYS_PER_YEAR = 365.25


@dataclass(frozen=True, slots=True)
class _CostAwareCPCV:
    """The net, annualised CPCV outcome: the path distribution + the pooled net return series."""

    distribution: PathDistribution
    net_returns: pd.Series  # per-event net strategy returns (one full-timeline path)


def build_validation_report(
    config: Config,
    repository: Repository,
    symbols: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    registry: ModelRegistry,
    tracker: ExperimentTracker,
    run_name: str = "p2.9-killgate",
) -> ValidationReport:
    """Run the full validation engine and emit the report + kill-gate verdict.

    Args:
        config: System config (model/pipeline/robustness/kill-gate knobs).
        repository: The store the real bars are read from (Parquet archive, by default).
        symbols: The universe symbols (the same pooled into the artifact).
        start: Inclusive window start (tz-aware IST).
        end: Inclusive window end (tz-aware IST).
        registry: Where the artifact lives (its latest version is judged).
        tracker: Where the report is logged (persistent MLflow for the real run; in-memory in test).
        run_name: Tracker run name.

    Returns:
        The :class:`ValidationReport` (carrying the seven-point :class:`KillGateVerdict`).

    Raises:
        PipelineError: If no symbol produced labellable events, or no artifact is registered.
    """
    pooled = build_pooled_dataset(config, repository, symbols, start, end)
    artifact, model_id = _load_artifact(config, registry)
    estimators = cross_family_estimators(config.model)

    round_trip = _representative_round_trip_cost(config, repository, symbols[0], start, end)
    periods_per_year = _events_per_year(pooled.n_obs, start, end)

    cpcv = _cost_aware_cpcv(config, pooled, estimators, round_trip, periods_per_year)
    net = cpcv.net_returns.to_numpy(dtype="float64")
    # The candidate-config panel feeds both the honest trial count (DSR) and the PBO — compute
    # it once (each config is one CPCV evaluation) and reuse.
    panel = _panel_net_returns(config, pooled, round_trip)
    trials = _trials_from_panel(panel)
    dsr = _deflated_sharpe(net, trials)
    pbo = _pbo_from_panel(panel)
    regime_means, regime_counts = _regime_evidence(artifact, pooled, cpcv.net_returns)
    walk_forward = _walk_forward(config, artifact, repository, symbols[0], start, end)
    robustness = run_robustness_battery(
        config, repository, symbols, start, end, registry=registry, tracker=tracker
    )
    robustness_detail = _robustness_detail(robustness)

    evidence = KillGateEvidence(
        cpcv_median_path_sharpe=cpcv.distribution.median,
        deflated_sharpe_ratio=dsr,
        pbo=pbo,
        fraction_negative_paths=cpcv.distribution.fraction_negative,
        worst_path_sharpe=cpcv.distribution.minimum,
        profit_factor=profit_factor(net),
        trade_concentration=trade_concentration(net),
        robustness_passed=robustness.passes,
        robustness_detail=robustness_detail,
        regime_mean_returns=regime_means,
        regime_observation_counts=regime_counts,
    )
    verdict = evaluate_kill_gate(evidence, config.kill_gate)
    report = _assemble_report(
        config,
        pooled,
        model_id,
        start,
        end,
        periods_per_year,
        trials.count,
        cpcv,
        dsr,
        pbo,
        walk_forward,
        robustness.passes,
        robustness_detail,
        regime_means,
        verdict,
    )
    _log_report(tracker, run_name, report)
    _logger.info(
        "validation report assembled",
        extra={
            "model_id": model_id,
            "verdict": verdict.verdict,
            "failed_criteria": [c.number for c in verdict.failed_criteria],
            "cpcv_median_sharpe": report.cpcv_median_sharpe,
            "dsr": dsr,
            "pbo": pbo,
        },
    )
    return report


def _representative_round_trip_cost(
    config: Config, repository: Repository, symbol: str, start: datetime, end: datetime
) -> float:
    """A representative all-in round-trip cost fraction from the real cost + slippage models.

    Samples a representative price (median decision-bar close) and liquidity (median volume) from
    one symbol over the window, sizes a notional from the per-trade risk budget, and asks the real
    cost + slippage models for the round-trip fraction. Falls back to neutral large-cap figures if
    the symbol has no bars (so the report still assembles).
    """
    decision_bars = resample_bars(
        repository.read_bars(symbol, start, end), config.market.decision_frequency_minutes
    )
    if decision_bars.empty:
        price, liquidity = 1000.0, 100000.0  # neutral large-cap fallback (no bars to sample)
    else:
        price = float(np.median(decision_bars["close"].to_numpy(dtype="float64")))
        liquidity = float(np.median(decision_bars["volume"].to_numpy(dtype="float64"))) or 1.0
    notional = config.risk.risk_per_trade_pct / 100.0 * config.backtest.initial_capital_inr
    quantity = max(1, round(notional / price))
    return round_trip_cost_fraction(
        IndianCostModel(config.costs),
        DepthAwareSlippage(config.slippage),
        price=price,
        quantity=quantity,
        liquidity=liquidity,
    )


def _events_per_year(n_obs: int, start: datetime, end: datetime) -> float:
    """Events per calendar year over the backfill window (the path-Sharpe annualisation factor)."""
    years = max((end - start).days / _DAYS_PER_YEAR, 1e-9)
    return n_obs / years


def _cost_aware_cpcv(
    config: Config,
    pooled: PooledDataset,
    estimators: Sequence[Estimator],
    round_trip: float,
    periods_per_year: float,
) -> _CostAwareCPCV:
    """Net, annualised CPCV path distribution + the pooled net per-event return series."""
    rob = config.robustness
    cpcv = CombinatorialPurgedCV(
        rob.cpcv_groups, rob.cpcv_test_groups, embargo_pct=rob.cpcv_embargo_pct
    )
    evaluation = evaluate_ensemble_under_cpcv(
        estimators,
        pooled.features,
        pooled.labels,
        pooled.label_times,
        pooled.forward_returns,
        cpcv,
        regime_features=pooled.regime_features,
        n_regimes=config.pipeline.n_regimes,
        method=config.pipeline.ensemble_method,
        periods_per_year=periods_per_year,
        round_trip_cost=round_trip,
        random_seed=config.model.random_seed,
    )
    return _CostAwareCPCV(
        distribution=evaluation.distribution, net_returns=evaluation.paths[0].dropna()
    )


def _trials_from_panel(panel: dict[str, pd.Series]) -> TrialTracker:
    """Record each panel config's net per-obs Sharpe — the honest trial count + variance for DSR."""
    tracker = TrialTracker()
    for name, series in panel.items():
        tracker.record_returns(name, series)  # per-observation Sharpe (DSR units)
    return tracker


def _deflated_sharpe(net: npt.NDArray[np.float64], trials: TrialTracker) -> float:
    """The Deflated Sharpe Ratio of the net returns against the honest trial count + variance."""
    observed, skew, kurt, n_obs = return_moments(net)
    return deflated_sharpe_ratio(
        observed, n_obs, skew, kurt, trials.sharpe_variance, max(trials.count, 1)
    )


def _pbo_from_panel(panel: dict[str, pd.Series]) -> float:
    """Probability of Backtest Overfitting over the candidate-config panel's net OOS series."""
    matrix = pd.DataFrame(panel)
    partitions = _cscv_partitions(matrix.shape[0])
    return probability_of_backtest_overfitting(matrix, n_partitions=partitions).pbo


def _panel_net_returns(
    config: Config, pooled: PooledDataset, round_trip: float
) -> dict[str, pd.Series]:
    """One net OOS return series per candidate configuration (the PBO / trial-count panel).

    Varies the genuinely overfit-prone knobs (tree capacity, learning rate, blend) — each a
    distinct "thing tried" — and evaluates it under a single-test-group CPCV so each yields one
    full-timeline net series. Cached on the call via a module attribute is avoided deliberately:
    the panel is recomputed where needed so the function stays pure.
    """
    rob = config.robustness
    cpcv = CombinatorialPurgedCV(rob.cpcv_groups, 1, embargo_pct=rob.cpcv_embargo_pct)
    base = config.model
    panel_configs = {
        "baseline": (base, config.pipeline.ensemble_method),
        "leaves_half": (
            base.model_copy(update={"num_leaves": max(2, base.num_leaves // 2)}),
            config.pipeline.ensemble_method,
        ),
        "leaves_double": (
            base.model_copy(update={"num_leaves": base.num_leaves * 2}),
            config.pipeline.ensemble_method,
        ),
        "lr_half": (
            base.model_copy(update={"learning_rate": base.learning_rate / 2.0}),
            config.pipeline.ensemble_method,
        ),
        "stack": (base, "stack"),
    }
    series: dict[str, pd.Series] = {}
    for name, (model_cfg, method) in panel_configs.items():
        evaluation = evaluate_ensemble_under_cpcv(
            cross_family_estimators(model_cfg),
            pooled.features,
            pooled.labels,
            pooled.label_times,
            pooled.forward_returns,
            cpcv,
            regime_features=pooled.regime_features,
            n_regimes=config.pipeline.n_regimes,
            method=method,
            round_trip_cost=round_trip,
            random_seed=config.model.random_seed,
        )
        series[name] = evaluation.paths[0].dropna()
    return series


def _regime_evidence(
    artifact: GatedEnsembleModel, pooled: PooledDataset, net_returns: pd.Series
) -> tuple[dict[int, float], dict[int, int]]:
    """Per-regime mean net return + counts (criterion 7), via the artifact's fitted regime gate."""
    regimes = artifact.regime_gate.mixture.predict(
        pooled.regime_features.loc[net_returns.index, list(artifact.regime_feature_names)]
    )
    n_regimes = artifact.regime_gate.mixture.n_components
    return regime_breakdown(regimes, net_returns.to_numpy(dtype="float64"), n_regimes)


def _walk_forward(
    config: Config,
    artifact: GatedEnsembleModel,
    repository: Repository,
    symbol: str,
    start: datetime,
    end: datetime,
) -> WalkForwardSummary:
    """Full-cost, next-bar-open walk-forward of the artifact's signal on one real symbol (P2.1)."""
    bars = repository.read_bars(symbol, start, end)
    decision_bars = resample_bars(bars, config.market.decision_frequency_minutes)
    targets = _sample_targets(config, artifact, symbol, bars, decision_bars)
    result = create_backtester(config).run(decision_bars, targets)
    equity = result.equity_curve.to_numpy(dtype="float64")
    if equity.size == 0:
        max_dd_pct = 0.0
    else:
        peak = np.maximum.accumulate(equity)
        max_dd_pct = float(np.max((peak - equity) / peak))
    return WalkForwardSummary(
        net_pnl=result.net_pnl,
        final_equity=result.final_equity,
        max_drawdown_pct=max_dd_pct,
        n_fills=result.n_fills,
    )


def _robustness_detail(r: RobustnessBatteryReport) -> str:
    """A compact one-line summary of the P2.8 battery's component flags (criterion 6 detail)."""
    return (
        f"knife_edge={r.parameter_sensitivity.is_knife_edge} "
        f"noise_persists={r.noise_injection.edge_persists} "
        f"order_robust={r.monte_carlo.order_robust} "
        f"cross_symbol={r.cross_symbol.generalizes} "
        f"synthetic_clean={not r.synthetic.edge_detected} "
        f"reconciled={r.reconciliation.reconciled}"
    )


def _cscv_partitions(n_obs: int) -> int:
    """Largest even CSCV partition count <= min(default, n_obs // 2), floored at 2."""
    candidate = min(DEFAULT_PARTITIONS, n_obs // 2)
    even = candidate - (candidate % 2)
    return max(even, 2)


def _assemble_report(
    config: Config,
    pooled: PooledDataset,
    model_id: str,
    start: datetime,
    end: datetime,
    periods_per_year: float,
    n_trials: int,
    cpcv: _CostAwareCPCV,
    dsr: float,
    pbo: float,
    walk_forward: WalkForwardSummary,
    robustness_passed: bool,
    robustness_detail: str,
    regime_means: dict[int, float],
    verdict: KillGateVerdict,
) -> ValidationReport:
    """Bundle the computed evidence into the frozen :class:`ValidationReport`."""
    interval = f"{config.market.decision_frequency_minutes}min"
    net = cpcv.net_returns.to_numpy(dtype="float64")
    return ValidationReport(
        model_id=model_id,
        data_version=data_version(list(pooled.symbols), start, end, interval),
        feature_set_version=config.features.feature_set_version,
        label_version=label_version(config.labeling),
        n_obs=pooled.n_obs,
        n_trials=n_trials,
        periods_per_year=periods_per_year,
        cpcv_num_paths=cpcv.distribution.num_paths,
        cpcv_median_sharpe=cpcv.distribution.median,
        cpcv_mean_sharpe=cpcv.distribution.mean,
        cpcv_std_sharpe=cpcv.distribution.std,
        cpcv_worst_sharpe=cpcv.distribution.minimum,
        cpcv_fraction_negative=cpcv.distribution.fraction_negative,
        deflated_sharpe_ratio=dsr,
        pbo=pbo,
        profit_factor=profit_factor(net),
        trade_concentration=trade_concentration(net),
        walk_forward=walk_forward,
        robustness_passed=robustness_passed,
        robustness_detail=robustness_detail,
        regime_mean_returns=regime_means,
        verdict=verdict,
    )


def _log_report(tracker: ExperimentTracker, run_name: str, report: ValidationReport) -> None:
    """Log the report's headline metrics + the verdict as a tracker run (the audit record)."""
    metrics = {
        "cpcv_median_sharpe": report.cpcv_median_sharpe,
        "cpcv_worst_sharpe": report.cpcv_worst_sharpe,
        "cpcv_fraction_negative": report.cpcv_fraction_negative,
        "deflated_sharpe_ratio": report.deflated_sharpe_ratio,
        "pbo": report.pbo,
        "profit_factor": report.profit_factor if np.isfinite(report.profit_factor) else -1.0,
        "trade_concentration": report.trade_concentration,
        "walk_forward_net_pnl": report.walk_forward.net_pnl,
        "verdict_pass": float(report.passed),
        "n_failed_criteria": float(len(report.verdict.failed_criteria)),
    }
    tracker.log_run(
        RunRecord(
            run_name=run_name,
            params={"n_trials": report.n_trials, "periods_per_year": report.periods_per_year},
            metrics=metrics,
            tags={
                "stage": "kill_gate",
                "model_id": report.model_id or "unregistered",
                "verdict": report.verdict.verdict,
                "data_version": report.data_version,
                "label_version": report.label_version,
            },
        )
    )
