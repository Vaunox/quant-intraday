"""Exceptions raised by the mechanical-edge research harness (Part VI / Phase 6).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed strategy spec from a missing/uncommitted
pre-registration from a trial-count source failure, instead of catching a bare
``RuntimeError``.
"""


class MechanismError(RuntimeError):
    """Base class for all mechanical-edge harness errors."""


class SpecError(MechanismError):
    """A :class:`~quant.research.mechanisms.spec.StrategySpec` input is malformed.

    For example a net-return series whose index does not align with the spec's
    ``label_times``, or an out-of-range event position.
    """


class TrialCountError(MechanismError):
    """A cumulative trial-count source is misconfigured or unavailable (P6.2).

    For example a request for a count over an empty experiment list, or an MLflow-backed
    source asked for with no ``mlflow`` install.
    """


class PreregistrationError(MechanismError):
    """A mechanism pre-registration is missing, malformed, or not yet committed (P6.3).

    A mechanism cannot enter Phase 7 without a committed pre-registration whose commit
    precedes its first test run; this is raised whenever that contract is not met.
    """
