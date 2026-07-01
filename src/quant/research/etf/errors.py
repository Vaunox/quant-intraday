"""Exceptions raised by the ETF research modules."""


class EtfUniverseError(RuntimeError):
    """The ETF universe config is missing, malformed, or queried for an unknown basket."""
