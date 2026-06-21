"""Exceptions raised by the validation harness (P2.1).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed cross-validation request from a bad
backtest input from any other failure instead of catching a bare ``RuntimeError``.
"""


class ValidationError(RuntimeError):
    """Base class for all validation-harness errors."""


class SplitError(ValidationError):
    """A cross-validation split request is malformed or infeasible.

    For example fewer observations than folds, an unsorted/duplicated label-time
    index, or a label window that ends before it starts.
    """


class CostModelError(ValidationError):
    """A cost-model input is invalid (e.g. a non-positive price or quantity)."""


class BacktestError(ValidationError):
    """A backtest input is malformed.

    For example multi-symbol bars in the single-symbol core, a target position
    indexed at a timestamp with no matching bar, or a non-integer share target.
    """


class MetricError(ValidationError):
    """A performance-statistic input is invalid.

    For example a Deflated/Probabilistic Sharpe Ratio asked for on fewer than two
    observations, or a negative trial variance.
    """


class PBOError(ValidationError):
    """A Probability-of-Backtest-Overfitting (CSCV) input is malformed.

    For example an odd number of CSCV partitions, fewer rows than partitions, or a
    performance matrix with fewer than two candidate strategies.
    """
