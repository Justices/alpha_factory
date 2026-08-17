"""组合策略 — 多策略串行/并行组合.

串行模式:
  - 策略1的输出作为策略2的输入
  - 适用场景: first_order → unary_template

并行模式:
  - 多策略独立执行，结果合并
  - 适用场景: template + test
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .base import CreationStrategy, StrategyConfig
from ..families import Task
from ..fields import ScalarField


@dataclass
class CompositeConfig(StrategyConfig):
    """组合策略配置."""

    name: str = "composite"
    strategies: Tuple[str, ...] = ()  # ("multi_stage", "template")
    mode: str = "serial"  # serial | parallel


class CompositeStrategy(CreationStrategy):
    """组合策略 — 多策略串行/并行组合."""

    def __init__(
        self,
        strategies: List[CreationStrategy],
        config: Optional[CompositeConfig] = None
    ):
        self.strategies = strategies
        self.config = config or CompositeConfig()

    @property
    def name(self) -> str:
        return "composite"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """组合策略执行."""
        if self.config.mode == "serial":
            return self._serial_execute(scalar_fields, group_fields, **kwargs)
        else:
            return self._parallel_execute(scalar_fields, group_fields, **kwargs)

    def _serial_execute(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """串行执行 — 前一策略输出作为后一策略输入."""
        current_fields = list(scalar_fields)
        all_tasks: List[Task] = []

        for strategy in self.strategies:
            tasks = strategy.generate_tasks(current_fields, group_fields, **kwargs)
            all_tasks.extend(tasks)

        return all_tasks

    def _parallel_execute(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """并行执行 — 独立执行后合并."""
        all_tasks: List[Task] = []

        for strategy in self.strategies:
            tasks = strategy.generate_tasks(scalar_fields, group_fields, **kwargs)
            all_tasks.extend(tasks)

        return all_tasks


__all__ = ["CompositeConfig", "CompositeStrategy"]