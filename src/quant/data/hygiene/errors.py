"""Exceptions raised by the data-hygiene jobs.

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed corporate action from a bad interval from
any other failure instead of catching a bare ``RuntimeError``.
"""


class HygieneError(RuntimeError):
    """Base class for all data-hygiene errors."""


class CorporateActionError(HygieneError):
    """A corporate action is malformed or cannot be applied to the series.

    For example a non-positive split/bonus ratio, or a cash dividend that exceeds the
    reference close (which would drive an adjusted price non-positive).
    """
