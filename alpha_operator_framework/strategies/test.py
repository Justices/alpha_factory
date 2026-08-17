"""测试类型策略 — 横截面算子测试因子信号.

典型用途:
  - 测试原始信号的稳定性
  - 评估不同参数下的表现
  - 横截面标准化对比
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .base import CreationStrategy, StrategyConfig
from ..families import Task
from ..fields import ScalarField


@dataclass
class TestStrategyConfig(StrategyConfig):
    """测试策略配置."""

    name: str = "test"
    test_operators: Tuple[str, ...] = ("rank", "quantile", "winsorize")
    quantile_bins: Tuple[int, ...] = (5, 10, 20, 50)
    winsorize_limits: Tuple[float, ...] = (0.01, 0.05, 0.1)
    include_neutralize: bool = True


class TestStrategy(CreationStrategy):
    """测试类型策略 — 横截面算子测试因子信号."""

    def __init__(self, config: Optional[TestStrategyConfig] = None):
        self.config = config or TestStrategyConfig()

    @property
    def name(self) -> str:
        return "test"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """生成测试算子任务."""
        tasks: List[Task] = []

        for sf in scalar_fields:
            for op in self.config.test_operators:
                if op == "rank":
                    tasks.append(self._build_test_task(
                        sf, f"rank({sf.expr})", "rank"
                    ))
                elif op == "quantile":
                    for bins in self.config.quantile_bins:
                        tasks.append(self._build_test_task(
                            sf, f"quantile({sf.expr}, {bins})", f"quantile_{bins}"
                        ))
                elif op == "winsorize":
                    for limit in self.config.winsorize_limits:
                        tasks.append(self._build_test_task(
                            sf, f"winsorize({sf.expr}, {limit})", f"winsorize_{limit}"
                        ))

            # 中性化测试
            if self.config.include_neutralize and group_fields:
                for g in group_fields:
                    tasks.append(self._build_test_task(
                        sf, f"neutralize({sf.expr}, {g})", "neutralize",
                        group=g
                    ))

        return tasks

    def _build_test_task(
        self,
        sf: ScalarField,
        expression: str,
        test_type: str,
        group: Optional[str] = None
    ) -> Task:
        """构建测试任务."""
        meta = {
            "strategy": "test",
            "test_type": test_type,
            "source_field": sf.expr,
        }
        if group:
            meta["group"] = group

        return Task(
            expression=expression,
            template_index=0,
            family="test",
            fields_per_alpha=1,
            expression_origin=f"test_{test_type}",
            decay=self.config.decay,
            base_fields=(sf.expr,),
            meta=meta,
        )


__all__ = ["TestStrategyConfig", "TestStrategy"]