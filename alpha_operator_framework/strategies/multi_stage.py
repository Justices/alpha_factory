"""多阶工厂策略 — first_order + unary_template.

典型流程:
  1. first_order: 对原始字段应用一阶算子（rank/zscore等）
  2. unary_template: 对一阶结果应用单字段模板

适用场景:
  - 经典一阶方法
  - 快速baseline
  - 性能对比参考
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .base import CreationStrategy, StrategyConfig
from ..database.models import Template
from ..families import Task
from ..fields import ScalarField


@dataclass
class MultiStageConfig(StrategyConfig):
    """多阶工厂配置."""

    name: str = "multi_stage"
    include_first_order: bool = True
    include_unary_template: bool = True
    first_order_ops: Tuple[str, ...] = (
        "rank", "zscore", "scale", "normalize", "winsorize",
        "neutralize", "outlier", "sigmoid"
    )
    unary_template_indices: Tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)


class MultiStageStrategy(CreationStrategy):
    """多阶工厂策略 — first_order + unary_template."""

    def __init__(self, config: Optional[MultiStageConfig] = None):
        self.config = config or MultiStageConfig()

    @property
    def name(self) -> str:
        return "multi_stage"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """生成多阶任务."""
        from ..families import unary_factory, first_order_task_factory

        tasks: List[Task] = []

        # 阶段1: first_order算子
        if self.config.include_first_order:
            first_order_tasks = first_order_task_factory(
                [sf.expr for sf in scalar_fields],
                ops_set=set(self.config.first_order_ops),
                decay=self.config.decay,
            )
            tasks.extend(first_order_tasks)

        # 阶段2: unary模板
        if self.config.include_unary_template:
            unary_tasks = unary_factory(
                [sf.expr for sf in scalar_fields],
            )
            if self.config.decay != 6.0:
                unary_tasks = [
                    Task(
                        expression=t.expression,
                        template_index=t.template_index,
                        family=t.family,
                        fields_per_alpha=t.fields_per_alpha,
                        expression_origin=t.expression_origin,
                        decay=self.config.decay,
                        base_fields=t.base_fields,
                        meta=t.meta,
                    )
                    for t in unary_tasks
                ]
            tasks.extend(unary_tasks)

        return tasks


__all__ = ["MultiStageConfig", "MultiStageStrategy"]