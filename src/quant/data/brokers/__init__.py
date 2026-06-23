"""Broker adapters: the ``BrokerAdapter`` Protocol and concrete implementations (Kite).

The ``BrokerAdapter`` Protocol itself lives in :mod:`quant.core.interfaces`; this
package holds the concrete Kite implementation and its supporting seams (session
auth, instrument resolution, rate limiting). Per Ground Rule 1 / Deep Dive #1 §0.3,
the ``kiteconnect`` SDK is imported only inside this package — see
:func:`quant.data.brokers.client.create_kite_client`.
"""

from quant.data.brokers.auth import (
    KITE_ACCESS_TOKEN_SECRET,
    KITE_API_KEY_SECRET,
    KITE_API_SECRET_SECRET,
    InMemoryTokenStore,
    KiteAuthenticator,
    TokenStore,
)
from quant.data.brokers.client import (
    KITE_INTERVALS,
    KiteClient,
    create_kite_client,
    normalize_interval,
)
from quant.data.brokers.errors import (
    BrokerError,
    InstrumentNotFoundError,
    SessionNotSeededError,
    UnsupportedIntervalError,
)
from quant.data.brokers.instruments import InstrumentRegistry
from quant.data.brokers.kite import KiteAdapter
from quant.data.brokers.morning_auth import seed_and_persist
from quant.data.brokers.rate_limit import RateLimiter, TokenBucketRateLimiter
from quant.data.brokers.ticker import (
    KiteTickerTransport,
    RawTicker,
    create_kite_ticker_transport,
)
from quant.data.brokers.verify import VerificationResult, verify_credentials

__all__ = [
    "KITE_ACCESS_TOKEN_SECRET",
    "KITE_API_KEY_SECRET",
    "KITE_API_SECRET_SECRET",
    "KITE_INTERVALS",
    "BrokerError",
    "InMemoryTokenStore",
    "InstrumentNotFoundError",
    "InstrumentRegistry",
    "KiteAdapter",
    "KiteAuthenticator",
    "KiteClient",
    "KiteTickerTransport",
    "RateLimiter",
    "RawTicker",
    "SessionNotSeededError",
    "TokenBucketRateLimiter",
    "TokenStore",
    "UnsupportedIntervalError",
    "VerificationResult",
    "create_kite_client",
    "create_kite_ticker_transport",
    "normalize_interval",
    "seed_and_persist",
    "verify_credentials",
]
