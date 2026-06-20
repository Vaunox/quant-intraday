"""Exceptions raised by the feature library."""


class FeatureError(RuntimeError):
    """Base class for feature-computation errors (e.g. no history at/before ``asof``)."""
