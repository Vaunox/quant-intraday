"""Exceptions raised by the model stack (P2.6).

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a malformed training matrix from a degenerate scoring
input from a missing optional tracking backend, instead of catching a bare ``RuntimeError``.
"""


class ModelError(RuntimeError):
    """Base class for all model-stack errors."""


class ModelTrainingError(ModelError):
    """A model-training input is malformed.

    For example an empty feature matrix, features and labels that do not align, a label
    vector that is not binary ``{0, 1}``, or a training fold that contains a single class.
    """


class CalibrationError(ModelError):
    """A probability-calibration input is invalid.

    For example mismatched score/label lengths, a non-finite score, or a request to
    calibrate on fewer than two points.
    """


class ScoringError(ModelError):
    """A classification-score input is invalid.

    For example mismatched prediction/label lengths, probabilities outside ``[0, 1]``, or a
    rank/threshold metric asked for on a single-class label vector.
    """


class ModelDependencyError(ModelError):
    """An optional model-stack backend was used but its package is not installed.

    MLflow is an optional experiment-tracking backend (it pins ``pandas<3``, like ArcticDB;
    see ``pyproject.toml``). Its client is imported lazily, and this is raised with install
    guidance if the import fails — the in-memory tracker is always available as the default.
    """
