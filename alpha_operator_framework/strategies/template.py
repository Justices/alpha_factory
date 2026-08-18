"""模板库策略 — 从数据库模板生成任务.

核心特性:
  - 支持placeholder和fixed两种模板类型
  - 按categories过滤字段
  - 支持group槽位
  - 支持枚举槽位（算子/参数）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .base import CreationStrategy, StrategyConfig
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.fields import ScalarField


@dataclass
class TemplateStrategyConfig(StrategyConfig):
    """模板库策略配置."""

    name: str = "template"
    families: Tuple[str, ...] = ("unary", "binary", "ternary", "quaternary")
    all_combinations: bool = True
    sample_n: int = 80
    template_categories: Tuple[str, ...] = ()  # 空表示全部
    templates: Optional[Sequence[Template]] = None  # 外部传入模板列表


class TemplateStrategy(CreationStrategy):
    """模板库策略 — 从数据库模板生成任务."""

    def __init__(self, config: Optional[TemplateStrategyConfig] = None):
        self.config = config or TemplateStrategyConfig()

    @property
    def name(self) -> str:
        return "template"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """从模板库生成任务."""
        from alpha_operator_framework.generation.template_library import template_creation_strategy

        # 获取模板列表
        templates = self.config.templates or kwargs.get("templates", [])
        if not templates:
            return []

        # 调用现有实现
        return template_creation_strategy(
            templates=templates,
            scalar_fields=scalar_fields,
            group_fields=group_fields or [],
            config=self.config,
        )


__all__ = ["TemplateStrategyConfig", "TemplateStrategy"]