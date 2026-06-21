"""Exceptions raised by the labeling jobs (P2.3).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed price/volatility input or an out-of-universe
event from any other failure instead of catching a bare ``RuntimeError``.
"""


class LabelingError(RuntimeError):
    """Base class for all labeling errors."""


class LabelingInputError(LabelingError):
    """A labeling input is malformed.

    For example a price series with a naive/unsorted index, non-positive prices, an event
    timestamp with no matching bar, or a volatility series that does not align to the bars.
    """
