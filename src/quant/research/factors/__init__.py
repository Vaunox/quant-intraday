"""Cross-sectional equity factor library (Phase 3X.2).

Price-only Phase-A factors (causal, point-in-time per-symbol transforms); cross-sectional
scoring is applied on top by the P3X.4 combiner. Phase-B fundamental factors are deferred
pending a point-in-time fundamentals feed.
"""

from quant.research.factors.price_factors import (
    amihud_illiquidity,
    low_volatility,
    momentum_12_1,
    residual_momentum,
    short_term_reversal,
)

__all__ = [
    "amihud_illiquidity",
    "low_volatility",
    "momentum_12_1",
    "residual_momentum",
    "short_term_reversal",
]
