"""Exceptions for the proprietary-data recorders (Part VI / Phase 9).

Specific, actionable error types (Ground Rule 7) so a caller can tell a malformed depth
snapshot from a missing earnings input from any other failure.
"""


class RecorderError(RuntimeError):
    """Base class for all Phase-9 recorder errors."""


class DepthRecorderError(RecorderError):
    """A live-depth recording input is malformed (e.g. a tz-naive snapshot timestamp)."""


class EventRecorderError(RecorderError):
    """An event-reaction recording input is malformed (e.g. a non-positive drift window)."""
