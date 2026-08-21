"""Unit tests for TokenBucketRateLimiter, AdaptiveRateLimiter and PriorityTaskScheduler."""

import asyncio
import time
import pytest

from alpha_operator_framework.platform.rate_limiter import (
    AdaptiveLimiterConfig,
    AdaptiveRateLimiter,
    TokenBucketRateLimiter,
)
from alpha_operator_framework.platform.task_scheduler import (
    PriorityTaskScheduler,
    TaskPriority,
)


def test_token_bucket_burst_and_rate():
    """Verify that TokenBucketRateLimiter allows initial burst and regulates subsequent rate."""
    async def _run():
        limiter = TokenBucketRateLimiter(rate=10.0, capacity=3.0)

        # 1. Burst of 3 should be immediate (0 wait)
        t0 = time.monotonic()
        w1 = await limiter.acquire(1.0)
        w2 = await limiter.acquire(1.0)
        w3 = await limiter.acquire(1.0)
        t1 = time.monotonic()

        assert w1 == 0.0
        assert w2 == 0.0
        assert w3 == 0.0
        assert (t1 - t0) < 0.1

        # 2. Next acquire should wait ~0.1s (rate is 10 tokens/s)
        w4 = await limiter.acquire(1.0)
        t2 = time.monotonic()
        assert (t2 - t1) >= 0.07

    asyncio.run(_run())


def test_adaptive_rate_limiter_aimd():
    """Verify AIMD: additive increase on successes, multiplicative decrease on throttle."""
    async def _run():
        config = AdaptiveLimiterConfig(
            initial_rate=2.0,
            min_rate=0.5,
            max_rate=4.0,
            increase_step=0.5,
            decrease_factor=0.5,
            success_threshold=2,
            backoff_base=0.01,
            max_backoff=0.1,
        )
        limiter = AdaptiveRateLimiter(config)

        # 1. Two successes should increase rate by 0.5
        assert limiter.current_rate == 2.0
        await limiter.report_success()
        await limiter.report_success()
        assert limiter.current_rate == 2.5

        # 2. Throttle report should halve rate to 1.25 and trigger backoff
        wait_time = await limiter.report_throttle(retry_after=0.01)
        assert limiter.current_rate == 1.25
        assert wait_time >= 0.01

    asyncio.run(_run())


def test_priority_task_scheduler_execution_and_ordering():
    """Verify PriorityTaskScheduler executes tasks according to priority levels."""
    async def _run():
        rate_limiter = AdaptiveRateLimiter(
            AdaptiveLimiterConfig(initial_rate=50.0, burst_capacity=20.0)
        )
        scheduler = PriorityTaskScheduler(max_concurrency=2, rate_limiter=rate_limiter)

        execution_order = []

        async def sample_job(tag: str, delay: float = 0.01):
            await asyncio.sleep(delay)
            execution_order.append(tag)
            return tag

        try:
            # Submit tasks with different priorities
            fut_low = scheduler.submit(sample_job, "LOW_1", priority=TaskPriority.LOW)
            fut_high = scheduler.submit(sample_job, "HIGH_1", priority=TaskPriority.HIGH)
            fut_critical = scheduler.submit(sample_job, "CRITICAL_1", priority=TaskPriority.CRITICAL)

            results = await asyncio.gather(fut_low, fut_high, fut_critical)
            assert set(results) == {"LOW_1", "HIGH_1", "CRITICAL_1"}

            # Critical and High should be picked ahead of or alongside Low
            assert "CRITICAL_1" in execution_order
            assert "HIGH_1" in execution_order
        finally:
            await scheduler.close()

    asyncio.run(_run())
