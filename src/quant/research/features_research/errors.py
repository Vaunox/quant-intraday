"""Exceptions raised by the feature-research jobs (P2.5).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can distinguish a malformed series or an infeasible stationarity
search from any other failure.
"""


class FeatureResearchError(RuntimeError):
    """Base class for all feature-research errors."""


class FracDiffError(FeatureResearchError):
    """A fractional-differentiation request is malformed or infeasible.

    For example a negative differencing order, a non-positive weight threshold, or a
    stationarity search where no candidate ``d`` achieves stationarity.
    """
