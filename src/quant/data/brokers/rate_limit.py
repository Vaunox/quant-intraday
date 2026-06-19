"""A token-bucket rate limiter for the broker's REST endpoints.

Kite enforces ~3 requests/second on data endpoints and ~10/second on order
endpoints (Deep Dive #1 §0.2); exceeding them returns HTTP 429. We self-throttle
*before* each call with a token bucket so correctness never depends on the broker
rejecting us. The clock and sleep are injectable, so the limiter is unit-testable
without real time: a fake clock advances when the limiter sleeps.
"""

import threading
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from quant.core.logging import get_logger

_logger = get_logger(__name__)

#: Tolerance when comparing accrued tokens against 1.0. Floating-point refill can
#: leave ``tokens`` a few ULPs below 1.0 (e.g. 0.999999999999999); without a
#: tolerance the computed wait shrinks below the clock's resolution, time stops
#: advancing, and the refill loop spins forever. Granting a token up to 1e-9 early
#: (≈ sub-nanosecond) is harmless for rate limiting and makes the loop terminating.
_TOKEN_EPSILON = 1e-9


@runtime_checkable
class RateLimiter(Protocol):
    """Throttles callers to a maximum sustained request rate."""

    def acquire(self) -> None:
        """Block until one request is permitted under the rate limit."""
        ...


class TokenBucketRateLimiter:
    """A thread-safe token-bucket limiter.

    Tokens refill continuously at ``rate_per_second`` up to ``capacity`` (the burst
    size, defaulting to one second's worth). :meth:`acquire` consumes one token,
    sleeping just long enough when none is available. Acquisition is serialised
    under a lock, giving one fair, global throttle shared across threads.
    """

    def __init__(
        self,
        rate_per_second: float,
        capacity: float | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Build a limiter.

        Args:
            rate_per_second: Sustained token refill rate (must be > 0).
            capacity: Maximum tokens (burst); defaults to ``rate_per_second``.
            monotonic: Monotonic clock source (injected in tests).
            sleep: Blocking sleep (injected in tests).

        Raises:
            ValueError: If ``rate_per_second`` or ``capacity`` is not positive.
        """
        if rate_per_second <= 0:
            raise ValueError(f"rate_per_second must be positive, got {rate_per_second!r}")
        if capacity is not None and capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity!r}")
        self._rate = float(rate_per_second)
        self._capacity = float(capacity) if capacity is not None else float(rate_per_second)
        self._monotonic = monotonic
        self._sleep = sleep
        self._tokens = self._capacity
        self._updated = monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        with self._lock:
            while True:
                now = self._monotonic()
                elapsed = now - self._updated
                self._updated = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0 - _TOKEN_EPSILON:
                    self._tokens -= 1.0
                    return
                # Sleep exactly long enough for the next token to accrue, then
                # re-check (the loop re-derives tokens from the elapsed time).
                wait = (1.0 - self._tokens) / self._rate
                _logger.debug("rate limit reached; waiting %.4fs for a token", wait)
                self._sleep(wait)
