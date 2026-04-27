"""Per-user token-bucket rate limiting.

Each authenticated user gets one bucket, sized to allow short bursts
plus a sustained rate. Defaults:

  capacity            30   (burst — back-to-back tool calls in a single
                            Claude turn rarely exceed this)
  refill_per_second   2    (sustained 120 req/min)

These are tunable via env vars `RATE_LIMIT_CAPACITY` and
`RATE_LIMIT_REFILL_PER_SECOND` so a deployment can dial up for paid
tiers without a redeploy.

In-memory only: a multi-replica deployment would need a shared store
(Redis) but until then a single Railway instance is the contention
boundary, and a per-process map is fine.
"""

from __future__ import annotations

import threading
import time

from mezake_mcp.config import get_settings


class TokenBucket:
    """Classic token bucket: `capacity` tokens, refilling at
    `refill_per_second`. Each call to `consume(n)` returns
    (allowed, retry_after_seconds).
    """

    __slots__ = ("capacity", "refill_per_second", "_tokens", "_last_refill", "_lock")

    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: int = 1) -> tuple[bool, float]:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self.capacity, self._tokens + elapsed * self.refill_per_second
            )
            self._last_refill = now
            if self._tokens >= n:
                self._tokens -= n
                return True, 0.0
            shortfall = n - self._tokens
            if self.refill_per_second <= 0:
                # No refill configured — bucket is permanently drained.
                return False, float("inf")
            return False, shortfall / self.refill_per_second


# ── Per-user bucket cache ─────────────────────────────────────────────────────

_buckets: dict[int, TokenBucket] = {}
_buckets_lock = threading.Lock()


def _bucket_for(user_id: int) -> TokenBucket:
    bucket = _buckets.get(user_id)
    if bucket is not None:
        return bucket
    with _buckets_lock:
        bucket = _buckets.get(user_id)
        if bucket is not None:
            return bucket
        s = get_settings()
        bucket = TokenBucket(s.rate_limit_capacity, s.rate_limit_refill_per_second)
        _buckets[user_id] = bucket
        return bucket


def consume_one(user_id: int) -> tuple[bool, float]:
    """Try to take one token from `user_id`'s bucket.
    Returns `(allowed, retry_after_seconds)`.
    """
    return _bucket_for(user_id).consume(1)


def reset_buckets() -> None:
    """Drop every bucket. For tests only."""
    with _buckets_lock:
        _buckets.clear()
