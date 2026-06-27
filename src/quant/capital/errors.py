"""Errors for the capital layer (portfolio construction, sizing, risk)."""


class CapitalError(Exception):
    """Raised on a malformed capital-layer input (fail loud — Ground Rule 7)."""
