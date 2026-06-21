"""Feature research: fractional differentiation and stationarity tooling.

P2.5 ships fractional differentiation (Deep Dive #2 §3.6): the binomial fixed-width-window
differencing :func:`~quant.research.features_research.frac_diff.frac_diff`, the
:func:`~quant.research.features_research.frac_diff.adf_test` stationarity check, and
:func:`~quant.research.features_research.frac_diff.min_ffd`, which selects the minimum ``d``
that achieves stationarity while preserving the maximum memory.
"""

from quant.research.features_research.errors import FeatureResearchError, FracDiffError
from quant.research.features_research.frac_diff import (
    ADFResult,
    FracDiffResult,
    adf_test,
    frac_diff,
    frac_diff_weights,
    min_ffd,
)

__all__ = [
    "ADFResult",
    "FeatureResearchError",
    "FracDiffError",
    "FracDiffResult",
    "adf_test",
    "frac_diff",
    "frac_diff_weights",
    "min_ffd",
]
