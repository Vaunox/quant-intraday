"""Cross-sectional equity factor library (Phase 3X.2).

Price-only Phase-A factors (causal, point-in-time per-symbol transforms); cross-sectional
scoring is applied on top by the P3X.4 combiner. Phase-B fundamental factors are deferred
pending a point-in-time fundamentals feed.
"""

from quant.research.factors.combine import (
    EqualWeightComposite,
    SignalCombiner,
    WeightedComposite,
    sector_neutral_composite,
)
from quant.research.factors.errors import FactorError
from quant.research.factors.price_factors import (
    amihud_illiquidity,
    low_volatility,
    momentum_12_1,
    residual_momentum,
    short_term_reversal,
)

__all__ = [
    "EqualWeightComposite",
    "FactorError",
    "SignalCombiner",
    "WeightedComposite",
    "amihud_illiquidity",
    "low_volatility",
    "momentum_12_1",
    "residual_momentum",
    "sector_neutral_composite",
    "short_term_reversal",
]
