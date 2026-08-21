"""优先级并发任务调度器 (Priority Task Scheduler).

功能:
  1. 任务优先级分级 (HIGH / NORMAL / LOW): 实时交互与提交优先于后台扫描
  2. 严格受控的并发槽位 (Bounded Concurrency Semaphore)
  3. 与 AdaptiveRateLimiter 联动，保证并发度与 QPS 双重安全
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Coroutine, Iterable, List, Optional, Sequence, Tuple

from alpha_operator_framework.platform.rate_limiter import AdaptiveRateLimiter


class TaskPriority(IntEnum):
    """任务优先级枚举 (数值越小优先级越高)."""

    CRITICAL = 0   # 紧急中断/鉴权
    HIGH = 1       # 用户交互/单因子提交/实时详情查询
    NORMAL = 5     # 深度优化回测 (Deepen)
    LOW = 10       # 广度扫描与元数据采集 (Survey / Ingest)


@dataclass(order=True)
class _PrioritizedItem:
    """包装优先级队列元素 (按 priority 升序比较)."""

    priority: int
    seq: int
    fn: Any = field(compare=False)
    args: tuple = field(compare=False)
    kwargs: dict = field(compare=False)
    future: asyncio.Future = field(compare=False)


class PriorityTaskScheduler:
    """带优先级与并发限额的异步任务调度器."""

    def __init__(
        self,
        max_concurrency: int = 4,
        rate_limiter: Optional[AdaptiveRateLimiter] = None,
    ):
        self.max_concurrency = max(1, int(max_concurrency))
        self.rate_limiter = rate_limiter or AdaptiveRateLimiter()
        self.queue: asyncio.PriorityQueue[_PrioritizedItem] = asyncio.PriorityQueue()
        self.semaphore = asyncio.Semaphore(self.max_concurrency)

        self._seq = 0
        self._workers: List[asyncio.Task] = []
        self._running = True

    async def _worker_loop(self) -> None:
        """后台 Worker 循环处理优先级队列任务."""
        while self._running:
            try:
                item = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                # 1. 申请流控令牌
                await self.rate_limiter.acquire(1.0)
                # 2. 申请并发槽位并执行
                async with self.semaphore:
                    res = await item.fn(*item.args, **item.kwargs)
                    if not item.future.done():
                        item.future.set_result(res)
                    await self.rate_limiter.report_success()
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                break
            except Exception as exc:
                err_str = str(exc).lower()
                if "429" in err_str or "too many requests" in err_str:
                    await self.rate_limiter.report_throttle()
                if not item.future.done():
                    item.future.set_exception(exc)
            finally:
                self.queue.task_done()

    def _ensure_workers(self) -> None:
        """按需初始化 Worker 协程池."""
        if not self._workers and self._running:
            for _ in range(self.max_concurrency):
                task = asyncio.create_task(self._worker_loop())
                self._workers.append(task)

    def submit(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        priority: TaskPriority = TaskPriority.NORMAL,
        **kwargs: Any,
    ) -> asyncio.Future:
        """提交任务到调度队列.

        Args:
            coro_fn: 异步可调用对象 (async function)
            *args: 位置参数
            priority: 优先级
            **kwargs: 关键字参数

        Returns:
            asyncio.Future 代表执行结果
        """
        self._ensure_workers()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._seq += 1

        item = _PrioritizedItem(
            priority=int(priority),
            seq=self._seq,
            fn=coro_fn,
            args=args,
            kwargs=kwargs,
            future=fut,
        )
        self.queue.put_nowait(item)
        return fut

    async def map(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        items: Iterable[Any],
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> List[Any]:
        """批量调度执行并等待全部完成返回结果列表."""
        futures = [self.submit(coro_fn, item, priority=priority) for item in items]
        return await asyncio.gather(*futures)

    async def close(self) -> None:
        """优雅关闭调度器."""
        self._running = False
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
