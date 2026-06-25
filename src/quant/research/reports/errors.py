"""Exceptions raised by the reports layer (P2.9).

Specific, actionable error types (Ground Rule 7) so a caller can distinguish a malformed report
request from a missing optional dependency (the QuantStats tearsheet backend).
"""


class ReportError(RuntimeError):
    """Base class for all reports-layer errors."""


class ReportDependencyError(ReportError):
    """An optional reporting backend (e.g. QuantStats) is not installed.

    Like MLflow/ArcticDB elsewhere, QuantStats is an operator-installed research-env tool, not a
    declared engine dependency; the validation report and kill-gate verdict are produced without
    it. Install it in the research env to also emit the HTML tearsheet.
    """
