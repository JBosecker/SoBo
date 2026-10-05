"""Token bucket limits. Without a client IP (cloudhook) we limit per session and
globally (plan 6)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.rate = rate
        self._clock = clock
        self._tokens = capacity
        self._updated = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def retry_after(self, cost: float = 1.0) -> float:
        self._refill()
        missing = cost - self._tokens
        return 0.0 if missing <= 0 else missing / self.rate


class KeyedRateLimiter:
    """One bucket per key (e.g. guest ID), LRU-bounded."""

    def __init__(
        self,
        capacity: float,
        rate: float,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.rate = rate
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(self.capacity, self.rate, self._clock)
            self._buckets[key] = bucket
            while len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)
        return bucket.allow(cost)

    def reset(self) -> None:
        self._buckets.clear()
