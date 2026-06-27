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


class BhavcopyError(IngestError):
    """A daily NSE bhavcopy could not be parsed (unrecognised schema or corrupt zip).

    The two historical bhavcopy layouts (legacy ``cm<DD><MON><YYYY>bhav.csv`` and the
    2024+ UDiFF file) are auto-detected by header; anything matching neither must fail
    loudly rather than silently yield an empty universe for that day.
    """
