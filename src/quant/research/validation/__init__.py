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
from quant.research.validation.slippage import DepthAwareSlippage
from quant.research.validation.splits import (
    Fold,
    PurgedKFold,
    embargo_size,
    purged_train_mask,
)
from quant.research.validation.trials import Trial, TrialTracker

__all__ = [
    "BacktestError",
    "BacktestResult",
    "Backtester",
    "CombinatorialPurgedCV",
    "CombinatorialSplit",
    "CostBreakdown",
    "CostModelError",
    "DepthAwareSlippage",
    "Fill",
    "Fold",
    "IndianCostModel",
    "MetricError",
    "PBOError",
    "PBOResult",
    "PathDistribution",
    "PurgedKFold",
    "SplitError",
    "Trial",
    "TrialTracker",
    "ValidationError",
    "create_backtester",
    "deflated_sharpe_ratio",
    "deflated_sharpe_ratio_from_returns",
    "embargo_size",
    "expected_maximum_sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "purged_train_mask",
    "return_moments",
    "sharpe_ratio",
]
