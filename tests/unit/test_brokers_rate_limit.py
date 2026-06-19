"""Tests for the token-bucket rate limiter (P1.1)."""

import pytest

from quant.data.brokers.rate_limit import RateLimiter, TokenBucketRateLimiter
from tests.unit.brokers_fakes import FakeClock


def test_satisfies_rate_limiter_protocol() -> None:
    limiter: RateLimiter = TokenBucketRateLimiter(3)
    assert isinstance(limiter, RateLimiter)


def test_burst_up_to_capacity_does_not_wait() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(3, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(3):  # capacity defaults to the rate (3)
        limiter.acquire()
    assert clock.sleeps == []


def test_waits_when_tokens_exhausted() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(3, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(3):
        limiter.acquire()
    limiter.acquire()  # 4th must wait one token's worth: 1/3 s
    assert clock.sleeps == [pytest.approx(1 / 3)]


def test_tokens_refill_over_elapsed_time() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(2, capacity=1, monotonic=clock.monotonic, sleep=clock.sleep)
    limiter.acquire()  # consumes the single token, no wait
    assert clock.sleeps == []
    clock.now += 0.5  # at 2 tokens/s, 0.5 s refills exactly one token
    limiter.acquire()
    assert clock.sleeps == []  # refilled token was available; still no wait


def test_sustained_rate_is_respected() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(5, capacity=1, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(10):
        limiter.acquire()
    # 1 free token (capacity) then 9 waits of 0.2 s each = 1.8 s of throttling.
    assert clock.now == pytest.approx(9 * 0.2)
    assert len(clock.sleeps) == 9


@pytest.mark.parametrize("bad_rate", [0, -1, -0.5])
def test_non_positive_rate_rejected(bad_rate: float) -> None:
    with pytest.raises(ValueError, match="rate_per_second"):
        TokenBucketRateLimiter(bad_rate)


def test_non_positive_capacity_rejected() -> None:
    with pytest.raises(ValueError, match="capacity"):
        TokenBucketRateLimiter(3, capacity=0)
