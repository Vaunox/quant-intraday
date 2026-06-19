"""Exceptions raised by the broker adapters.

Specific, actionable error types (Ground Rule 7: fail loudly with clear, specific
exceptions) so a caller can tell a missing session from an unknown symbol from an
unsupported interval, instead of catching a bare ``RuntimeError``.
"""


class BrokerError(RuntimeError):
    """Base class for all broker-adapter errors."""


class SessionNotSeededError(BrokerError):
    """A market-data or account call was attempted before the session was seeded.

    The Kite access token expires daily and must be re-seeded each morning via the
    manual login flow (see :class:`quant.data.brokers.auth.KiteAuthenticator` and
    ``docs/runbooks/kite_session.md``).
    """


class InstrumentNotFoundError(BrokerError):
    """No instrument token is known for the requested ``(symbol, exchange)``."""


class UnsupportedIntervalError(BrokerError):
    """The requested candle interval is not a supported Kite interval."""
