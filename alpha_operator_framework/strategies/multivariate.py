"""多元字段策略 — 多字段组合构建.

适用场景:
  - 多因子联合信号
  - 跨category字段组合（如 analyst + pv）
  - 复合因子构建
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from .base import CreationStrategy, StrategyConfig
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.fields import ScalarField


@dataclass
class MultivariateConfig(StrategyConfig):
    """多元字段构建配置."""

    name: str = "multivariate"
    min_fields: int = 2
    max_fields: int = 5
    combination_limit: int = 1000
    cross_category: bool = False  # 是否跨category组合


class MultivariateStrategy(CreationStrategy):
    """多元字段策略 — 多字段组合构建."""

    def __init__(self, config: Optional[MultivariateConfig] = None):
        self.config = config or MultivariateConfig()

    @property
    def name(self) -> str:
        return "multivariate"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """生成多元字段任务."""
        tasks: List[Task] = []

        # 按category分组
        by_category: Dict[str, List[ScalarField]] = {}
        for sf in scalar_fields:
            cat = sf.category or "default"
            by_category.setdefault(cat, []).append(sf)

        # 组合策略
        if self.config.cross_category:
            # 跨category组合
            all_fields = list(scalar_fields)
            for n_fields in range(self.config.min_fields, self.config.max_fields + 1):
                for combo in combinations(all_fields, n_fields):
                    if len(tasks) >= self.config.combination_limit:
                        break
                    task = self._build_multivariate_task(combo)
                    tasks.append(task)
        else:
            # 同category组合
            for cat, fields in by_category.items():
                for n_fields in range(self.config.min_fields, min(self.config.max_fields + 1, len(fields) + 1)):
                    for combo in combinations(fields, n_fields):
                        if len(tasks) >= self.config.combination_limit:
                            break
                        task = self._build_multivariate_task(combo)
                        tasks.append(task)

        return tasks

    def _build_multivariate_task(self, fields: Tuple[ScalarField, ...]) -> Task:
        """构建多元字段任务."""
        expr = f"rank(add({', '.join(f.expr for f in fields)}))"
        return Task(
            expression=expr,
            template_index=99,
            family="multivariate",
            fields_per_alpha=len(fields),
            expression_origin="multivariate",
            decay=self.config.decay,
            base_fields=tuple(f.expr for f in fields),
            meta={"strategy": "multivariate", "field_count": len(fields)},
        )


__all__ = ["MultivariateConfig", "MultivariateStrategy"]