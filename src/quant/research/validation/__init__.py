"""Validation: purged CV, embargo, CPCV, DSR, PBO, cost backtester, and robustness.

P2.1 ships the *judge before the contestants* (Deep Dive #2 §4b): the purged k-fold +
embargo splitter (:mod:`~quant.research.validation.splits`) and the realistic,
next-bar-open backtest core (:mod:`~quant.research.validation.backtest`) with the full
Indian cost model (:mod:`~quant.research.validation.costs`) and size/depth-aware slippage
(:mod:`~quant.research.validation.slippage`). CPCV / DSR / PBO build on these in P2.2.
"""

from quant.research.validation.backtest import (
    Backtester,
    BacktestResult,
    Fill,
    create_backtester,
)
from quant.research.validation.costs import CostBreakdown, IndianCostModel
from quant.research.validation.errors import (
    BacktestError,
    CostModelError,
    SplitError,
    ValidationError,
)
from quant.research.validation.slippage import DepthAwareSlippage
from quant.research.validation.splits import Fold, PurgedKFold, embargo_size

__all__ = [
    "BacktestError",
    "BacktestResult",
    "Backtester",
    "CostBreakdown",
    "CostModelError",
    "DepthAwareSlippage",
    "Fill",
    "Fold",
    "IndianCostModel",
    "PurgedKFold",
    "SplitError",
    "ValidationError",
    "create_backtester",
    "embargo_size",
]
