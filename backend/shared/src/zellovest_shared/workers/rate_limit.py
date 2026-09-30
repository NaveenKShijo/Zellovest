"""Token bucket rate limiter for API calls."""

import time
from threading import Lock


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter.

    Allows burst up to capacity, then enforces steady rate.
    """

    def __init__(self, rate_per_second: float, capacity: int | None = None):
        self._rate = rate_per_second
        self._capacity = capacity or int(rate_per_second * 2)  # allow 2s burst
        self._tokens = float(self._capacity)
        self._last = time.monotonic()
        self._lock = Lock()

    def acquire(self, tokens: int = 1) -> float:
        """Acquire tokens, blocking until available. Returns wait time."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return 0.0

            deficit = tokens - self._tokens
            wait = deficit / self._rate
            self._tokens = 0.0
            return wait

    def try_acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens without blocking. Returns True if successful."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False