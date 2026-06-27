"""Mechanical-edge research harness (Part VI / Phase 6).

A thin specification + discipline layer that lets **non-directional / event-driven** strategies
be expressed and judged by the **existing** CPCV / DSR / PBO / kill-gate / robustness engine —
the validation engine is *reused, not rebuilt* (Part VI mandate). Three pieces:

* **P6.1 — strategy specification** (:mod:`~quant.research.mechanisms.spec`): a
  :class:`StrategySpec` Protocol + the adapter that turns a mechanism's per-event net returns into
  the ``BacktestFn`` the CPCV engine already consumes, plus the kill-gate evidence assembler.
* **P6.2 — honest cumulative trial count** (:mod:`~quant.research.mechanisms.trials`): the DSR
  trial count is pulled automatically from a live cumulative source; the hard-coded-N path is
  removed and forbidden.
* **P6.3 — pre-registration** (:mod:`~quant.research.mechanisms.preregistration`): a mechanism's
  hypothesis + pre-committed thresholds must be committed to git before its first test run.
"""

from quant.research.mechanisms.errors import (
    MechanismDataError,
    MechanismError,
    PreregistrationError,
    SpecError,
    TrialCountError,
)
from quant.research.mechanisms.index_rebalance import (
    IndexRebalanceSpec,
    ReconstitutionEvent,
    evaluate_index_rebalance,
    load_reconstitution_events,
)
from quant.research.mechanisms.preregistration import (
    CommittedPreregistration,
    Preregistration,
    load_preregistration,
    parse_preregistration,
    require_preregistration,
)
from quant.research.mechanisms.spec import (
    MechanismEvaluation,
    SeriesStrategySpec,
    StrategySpec,
    evaluate_spec_under_cpcv,
    mechanism_kill_gate_evidence,
    spec_backtest_fn,
    validate_spec_timeline,
)
from quant.research.mechanisms.trials import (
    MlflowTrialCountSource,
    TrackerTrialCountSource,
    TrialCountSource,
    create_mlflow_trial_count_source,
    deflated_sharpe_auto,
)

__all__ = [
    "CommittedPreregistration",
    "IndexRebalanceSpec",
    "MechanismDataError",
    "MechanismError",
    "MechanismEvaluation",
    "MlflowTrialCountSource",
    "Preregistration",
    "PreregistrationError",
    "ReconstitutionEvent",
    "SeriesStrategySpec",
    "SpecError",
    "StrategySpec",
    "TrackerTrialCountSource",
    "TrialCountError",
    "TrialCountSource",
    "create_mlflow_trial_count_source",
    "deflated_sharpe_auto",
    "evaluate_index_rebalance",
    "evaluate_spec_under_cpcv",
    "load_preregistration",
    "load_reconstitution_events",
    "mechanism_kill_gate_evidence",
    "parse_preregistration",
    "require_preregistration",
    "spec_backtest_fn",
    "validate_spec_timeline",
]
