"""Bounded idempotent retry coordination for infrastructure workers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable


class RetryWorker:
    def __init__(self, *, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self._attempts: Counter[str] = Counter()

    def run(self, idempotency_key: str, operation: Callable[[], bool]) -> bool:
        if self._attempts[idempotency_key] >= self.max_attempts:
            return False
        self._attempts[idempotency_key] += 1
        return bool(operation())
