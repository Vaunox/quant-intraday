"""Exceptions raised by the data-ingestion jobs.

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a corrupt resume-checkpoint from any other failure
instead of catching a bare ``RuntimeError``.
"""


class IngestError(RuntimeError):
    """Base class for all data-ingestion errors."""


class BackfillCheckpointError(IngestError):
    """The backfill resume-checkpoint file exists but is malformed or unreadable.

    The checkpoint records how far each ``(symbol, interval)`` backfill has completed
    (so a re-run skips finished symbols). A corrupt file must fail loudly rather than
    be silently ignored, which would re-fetch everything or, worse, skip incorrectly.
    """
