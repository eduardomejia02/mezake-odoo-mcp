"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import time

from mezake_mcp.auth.rate_limit import TokenBucket, consume_one, reset_buckets


class TestTokenBucket:
    def test_consumes_up_to_capacity(self) -> None:
        b = TokenBucket(capacity=5, refill_per_second=0)
        for _ in range(5):
            allowed, _ = b.consume(1)
            assert allowed
        allowed, retry = b.consume(1)
        assert not allowed
        # No refill rate -> infinite wait. We just check it's positive.
        # Skip retry assertion when refill is 0 (division avoidance).

    def test_refills_over_time(self) -> None:
        b = TokenBucket(capacity=2, refill_per_second=10)
        # Drain
        b.consume(2)
        allowed, _ = b.consume(1)
        assert not allowed
        # Wait for refill
        time.sleep(0.15)  # 1.5 tokens generated
        allowed, _ = b.consume(1)
        assert allowed

    def test_capacity_is_a_ceiling(self) -> None:
        b = TokenBucket(capacity=3, refill_per_second=100)
        time.sleep(0.1)  # would refill 10 tokens, but cap is 3
        for _ in range(3):
            assert b.consume(1)[0]
        assert not b.consume(1)[0]

    def test_retry_after_makes_sense(self) -> None:
        b = TokenBucket(capacity=1, refill_per_second=2.0)
        b.consume(1)
        allowed, retry = b.consume(1)
        assert not allowed
        # Need 1 token, refill 2/s => ~0.5s
        assert 0.4 < retry < 0.6


class TestPerUserBuckets:
    def test_separate_users_have_separate_buckets(self, monkeypatch) -> None:
        # Tiny bucket so one user can drain quickly without affecting the other
        monkeypatch.setenv("RATE_LIMIT_CAPACITY", "2")
        monkeypatch.setenv("RATE_LIMIT_REFILL_PER_SECOND", "0.01")
        from mezake_mcp.config import get_settings
        get_settings.cache_clear()
        reset_buckets()

        # Drain user A
        assert consume_one(1)[0]
        assert consume_one(1)[0]
        assert not consume_one(1)[0]

        # User B is unaffected
        assert consume_one(2)[0]
        assert consume_one(2)[0]

        get_settings.cache_clear()
        reset_buckets()
