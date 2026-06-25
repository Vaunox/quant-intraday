"""Reports: validation report, tearsheet, and the seven-point kill-gate emitter (P2.9).

The Layer-2 output contract (Deep Dive #2 §4b.8): one report per strategy carrying the CPCV
path-Sharpe distribution, Deflated Sharpe, PBO, honest trial count, full-cost walk-forward equity,
and the robustness battery results — sufficient to make a binary trade/don't-trade decision, which
the seven-point :class:`~quant.research.reports.killgate.KillGateVerdict` emits.

The pure pieces live here (the gate, the report bundle + stat primitives, the optional QuantStats
tearsheet); the orchestration that runs the model + validation engine to fill them is
:mod:`quant.research.pipeline.validation`.
"""

from quant.research.reports.errors import ReportDependencyError, ReportError
from quant.research.reports.killgate import (
    KillGateCriterion,
    KillGateEvidence,
    KillGateVerdict,
    evaluate_kill_gate,
)
from quant.research.reports.report import (
    ValidationReport,
    WalkForwardSummary,
    net_event_returns,
    profit_factor,
    regime_breakdown,
    round_trip_cost_fraction,
    trade_concentration,
)
from quant.research.reports.tearsheet import write_quantstats_tearsheet

__all__ = [
    "KillGateCriterion",
    "KillGateEvidence",
    "KillGateVerdict",
    "ReportDependencyError",
    "ReportError",
    "ValidationReport",
    "WalkForwardSummary",
    "evaluate_kill_gate",
    "net_event_returns",
    "profit_factor",
    "regime_breakdown",
    "round_trip_cost_fraction",
    "trade_concentration",
    "write_quantstats_tearsheet",
]
