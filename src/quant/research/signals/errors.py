"""Exceptions raised by the signal modules (Phase 3T).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed bar/parameter input from any other failure
instead of catching a bare ``RuntimeError``.
"""


class SignalError(RuntimeError):
    """Base class for all signal-module errors."""


class SignalInputError(SignalError):
    """A signal input is malformed.

    For example a non-positive Donchian/ATR window, a non-positive equity/cash/price into
    the sizer, or a stop multiple that is not positive.
    """
