"""异步自适应令牌桶流控器 (Adaptive Token Bucket Rate Limiter).

功能:
  1. 令牌桶算法 (Token Bucket): 精确控制 QPS 与突发容量 (Burst Capacity)
  2. 动态拥塞控制 (AIMD: 加法递增 / 乘法递减):
     - 捕获 429 Too Many Requests / 503 限流时，乘法降速并启动带抖动的指数退避 (Exponential Backoff with Jitter)
     - 连续请求成功时，加法缓慢探测提升 QPS 直至达到上限
  3. 异步上下文管理器与自动限流容错
"""

from __future__ import annotations

import asyncio
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional


class TokenBucketRateLimiter:
    """纯异步线程/协程安全令牌桶流控器."""

    def __init__(self, rate: float = 2.0, capacity: float = 4.0):
        """
        Args:
            rate: 令牌生成速率 (tokens/second, 即 QPS)
            capacity: 桶容量 (允许的最大突发请求量)
        """
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    def update_rate(self, new_rate: float, new_capacity: Optional[float] = None) -> None:
        """动态调整速率与桶容量."""
        self.rate = max(0.01, float(new_rate))
        if new_capacity is not None:
            self.capacity = max(1.0, float(new_capacity))
            self.tokens = min(self.tokens, self.capacity)

    async def acquire(self, tokens: float = 1.0) -> float:
        """获取令牌. 若令牌不足则异步等待补充，返回等待时间(秒)."""
        tokens = float(tokens)
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now

            # 注入新生成的令牌 (不超过容量)
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            # 令牌不足，计算所需等待时间
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            self.tokens = 0.0
            # 预扣时间戳
            self.last_update = now + wait_time

        if wait_time > 0:
            await asyncio.sleep(wait_time)
        return wait_time

    async def __aenter__(self):
        await self.acquire(1.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@dataclass
class AdaptiveLimiterConfig:
    """自适应流控配置."""

    initial_rate: float = 2.0        # 初始 QPS
    min_rate: float = 0.2            # 最小保底 QPS
    max_rate: float = 8.0            # 最大上限 QPS
    burst_capacity: float = 4.0      # 突发容量
    increase_step: float = 0.2       # 每次加法递增步长
    decrease_factor: float = 0.5     # 每次乘法递减系数 (减半)
    success_threshold: int = 5       # 连续多少次成功后提升一次速率
    backoff_base: float = 2.0        # 初始退避秒数
    max_backoff: float = 60.0        # 最大退避秒数


class AdaptiveRateLimiter:
    """具备 AIMD 动态拥塞控制与智能退避重试的自适应流控器."""

    def __init__(self, config: Optional[AdaptiveLimiterConfig] = None):
        self.config = config or AdaptiveLimiterConfig()
        self.current_rate = self.config.initial_rate
        self.bucket = TokenBucketRateLimiter(rate=self.current_rate, capacity=self.config.burst_capacity)

        self._consecutive_success = 0
        self._current_backoff = self.config.backoff_base
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> float:
        """获取执行许可."""
        return await self.bucket.acquire(tokens)

    async def report_success(self) -> None:
        """报告一次成功调用 (触发慢启动 / 拥塞避免加法递增)."""
        async with self._lock:
            self._consecutive_success += 1
            if self._consecutive_success >= self.config.success_threshold:
                self._consecutive_success = 0
                if self.current_rate < self.config.max_rate:
                    self.current_rate = min(self.config.max_rate, self.current_rate + self.config.increase_step)
                    self.bucket.update_rate(self.current_rate)
            # 恢复初始退避基数
            self._current_backoff = self.config.backoff_base

    async def report_throttle(self, retry_after: Optional[float] = None) -> float:
        """报告一次 429/503 限流 (触发乘法减速与带抖动的指数退避).

        Returns:
            需要休眠的等待秒数
        """
        async with self._lock:
            self._consecutive_success = 0
            # 乘法降低速率
            self.current_rate = max(self.config.min_rate, self.current_rate * self.config.decrease_factor)
            self.bucket.update_rate(self.current_rate)

            # 计算退避时间 (平台返回的 Retry-After 优先，加 0.1~1.0s 随机抖动防雪崩)
            jitter = random.uniform(0.1, 1.0)
            if retry_after is not None and retry_after > 0:
                sleep_seconds = retry_after + jitter
            else:
                sleep_seconds = min(self.config.max_backoff, self._current_backoff + jitter)
                self._current_backoff = min(self.config.max_backoff, self._current_backoff * 2.0)

        await asyncio.sleep(sleep_seconds)
        return sleep_seconds

    @asynccontextmanager
    async def request_guard(self) -> AsyncGenerator[AdaptiveRateLimiter, None]:
        """请求守卫上下文: 自动申请令牌，并在发生限流异常时自动报告降速."""
        await self.acquire(1.0)
        try:
            yield self
            await self.report_success()
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "too many requests" in err_str or "503" in err_str:
                await self.report_throttle()
            raise
