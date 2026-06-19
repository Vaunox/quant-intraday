"""Broker adapters: the ``BrokerAdapter`` Protocol and concrete implementations (Kite).

The ``BrokerAdapter`` Protocol itself lives in :mod:`quant.core.interfaces`; this
package holds the concrete Kite implementation and its supporting seams (session
auth, instrument resolution, rate limiting). Per Ground Rule 1 / Deep Dive #1 §0.3,
the ``kiteconnect`` SDK is imported only inside this package — see
:func:`quant.data.brokers.client.create_kite_client`.
"""

from quant.data.brokers.auth import (
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
from quant.data.brokers.rate_limit import RateLimiter, TokenBucketRateLimiter

__all__ = [
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
    "RateLimiter",
    "SessionNotSeededError",
    "TokenBucketRateLimiter",
    "TokenStore",
    "UnsupportedIntervalError",
    "create_kite_client",
    "normalize_interval",
]
