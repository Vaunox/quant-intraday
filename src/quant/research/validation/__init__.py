"""Validation: purged CV, embargo, CPCV, DSR, PBO, cost backtester, and robustness.

P2.1 shipped the *judge before the contestants* (Deep Dive #2 §4b): the purged k-fold +
embargo splitter (:mod:`~quant.research.validation.splits`) and the realistic,
next-bar-open backtest core (:mod:`~quant.research.validation.backtest`) with the full
Indian cost model (:mod:`~quant.research.validation.costs`) and size/depth-aware slippage
(:mod:`~quant.research.validation.slippage`).

P2.2 adds the "is the edge real?" toolkit: Combinatorial Purged CV with path
reconstruction (:mod:`~quant.research.validation.cpcv`), the Deflated/Probabilistic Sharpe
Ratios (:mod:`~quant.research.validation.metrics`), the Probability of Backtest
Overfitting via CSCV (:mod:`~quant.research.validation.pbo`), and an honest trial-count
log for the DSR (:mod:`~quant.research.validation.trials`).

P2.8 adds the "stress the edge" battery: parameter sensitivity, Monte Carlo trade shuffle,
noise injection, cross-symbol validation, and synthetic-data backtesting
(:mod:`~quant.research.validation.robustness`), plus a second, independent vectorised engine
reconciled against the event-driven core (:mod:`~quant.research.validation.reconcile`).
"""

from quant.research.validation.backtest import (
    Backtester,
    BacktestResult,
    Fill,
    create_backtester,
)
from quant.research.validation.costs import CostBreakdown, IndianCostModel
from quant.research.validation.cpcv import (
    CombinatorialPurgedCV,
    CombinatorialSplit,
    PathDistribution,
)
from quant.research.validation.errors import (
    BacktestError,
    CostModelError,
    MetricError,
    PBOError,
    ReconciliationError,
    RobustnessError,
    SplitError,
    ValidationError,
)
from quant.research.validation.metrics import (
    deflated_sharpe_ratio,
    deflated_sharpe_ratio_from_returns,
    expected_maximum_sharpe_ratio,
    probabilistic_sharpe_ratio,
    return_moments,
    sharpe_ratio,
)
from quant.research.validation.pbo import PBOResult, probability_of_backtest_overfitting
from quant.research.validation.reconcile import (
    BacktestEngine,
    ReconciliationReport,
    VectorizedBacktester,
    create_vectorized_backtester,
    reconcile_engines,
)
from quant.research.validation.robustness import (
    CrossSymbolReport,
    MonteCarloShuffleReport,
    NoiseInjectionReport,
    ParameterSensitivityReport,
    StrategyDataset,
    SyntheticDataReport,
    cross_symbol_validation,
    geometric_brownian_bars,
    max_drawdown,
    monte_carlo_shuffle,
    noise_injection,
    parameter_sensitivity,
    synthetic_data_backtest,
)
from quant.research.validation.slippage import DepthAwareSlippage
from quant.research.validation.splits import (
    Fold,
    PurgedKFold,
    embargo_size,
    purged_train_mask,
)
from quant.research.validation.trials import Trial, TrialTracker

__all__ = [
    "BacktestEngine",
    "BacktestError",
    "BacktestResult",
    "Backtester",
    "CombinatorialPurgedCV",
    "CombinatorialSplit",
    "CostBreakdown",
    "CostModelError",
    "CrossSymbolReport",
    "DepthAwareSlippage",
    "Fill",
    "Fold",
    "IndianCostModel",
    "MetricError",
    "MonteCarloShuffleReport",
    "NoiseInjectionReport",
    "PBOError",
    "PBOResult",
    "ParameterSensitivityReport",
    "PathDistribution",
    "PurgedKFold",
    "ReconciliationError",
    "ReconciliationReport",
    "RobustnessError",
    "SplitError",
    "StrategyDataset",
    "SyntheticDataReport",
    "Trial",
    "TrialTracker",
    "ValidationError",
    "VectorizedBacktester",
    "create_backtester",
    "create_vectorized_backtester",
    "cross_symbol_validation",
    "deflated_sharpe_ratio",
    "deflated_sharpe_ratio_from_returns",
    "embargo_size",
    "expected_maximum_sharpe_ratio",
    "geometric_brownian_bars",
    "max_drawdown",
    "monte_carlo_shuffle",
    "noise_injection",
    "parameter_sensitivity",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "purged_train_mask",
    "reconcile_engines",
    "return_moments",
    "sharpe_ratio",
    "synthetic_data_backtest",
]
