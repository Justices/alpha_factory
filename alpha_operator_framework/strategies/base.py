"""创建策略基类 — 定义统一的任务生成接口."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..families import Task
from ..fields import ScalarField


@dataclass
class StrategyConfig:
    """策略配置基类."""

    decay: float = 6.0
    name: str = ""


class CreationStrategy(ABC):
    """创建策略抽象基类 — 定义统一的任务生成接口."""

    @abstractmethod
    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        """生成任务列表.

        Args:
            scalar_fields: 标量字段列表（带category）
            group_fields: GROUP字段列表
            **kwargs: 策略特定参数

        Returns:
            Task列表
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称."""
        pass


__all__ = ["StrategyConfig", "CreationStrategy"]