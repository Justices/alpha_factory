"""创建策略 — 组件化的任务生成策略.

策略类型:
  1. MultiStageStrategy: 多阶工厂 (first_order + unary_template)
  2. MultivariateStrategy: 多元字段构建
  3. TemplateStrategy: 模板库构建
  4. TestStrategy: 测试类型 (横截面算子 rank/quantile/winsorize)

设计原则:
  * 策略可插拔: 通过配置切换
  * 策略可组合: 多策略串行/并行
  * 策略可配置: 每个策略有独立配置
  * 统一输出: 都返回 List[Task]
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .database.models import Template
from .families import Task
from .fields import ScalarField


# ---------------------------------------------------------------------------
# 策略抽象基类
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 1. 多阶工厂策略
# ---------------------------------------------------------------------------

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
    """多阶工厂策略 — first_order + unary_template.

    典型流程:
      1. first_order: 对原始字段应用一阶算子（rank/zscore等）
      2. unary_template: 对一阶结果应用单字段模板
    """

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
        from .families import unary_factory, first_order_task_factory

        tasks: List[Task] = []

        # 阶段1: first_order算子
        if self.config.include_first_order:
            first_order_tasks = first_order_task_factory(
                [sf.expr for sf in scalar_fields],
                ops_set=set(self.config.first_order_ops),
                decay=self.config.decay,
            )
            tasks.extend(first_order_tasks)

        # 阶段2: unary模板（可选：只用特定index）
        if self.config.include_unary_template:
            unary_tasks = unary_factory(
                [sf.expr for sf in scalar_fields],
            )
            # 手动设置decay
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


# ---------------------------------------------------------------------------
# 2. 多元字段策略
# ---------------------------------------------------------------------------

@dataclass
class MultivariateConfig(StrategyConfig):
    """多元字段构建配置."""

    name: str = "multivariate"
    min_fields: int = 2
    max_fields: int = 5
    combination_limit: int = 1000
    cross_category: bool = False  # 是否跨category组合


class MultivariateStrategy(CreationStrategy):
    """多元字段策略 — 多字段组合构建.

    适用场景:
      - 多因子联合信号
      - 跨category字段组合（如 analyst + pv）
      - 复合因子构建
    """

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
        from itertools import combinations

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
                    # TODO: 实现多元表达式模板
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
        """构建多元字段任务 — 待实现具体模板."""
        # TODO: 实现多元表达式模板（如线性组合、PCA等）
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


# ---------------------------------------------------------------------------
# 3. 模板库策略
# ---------------------------------------------------------------------------

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
    """模板库策略 — 从数据库模板生成任务.

    核心特性:
      - 支持placeholder和fixed两种模板类型
      - 按categories过滤字段
      - 支持group槽位
      - 支持枚举槽位（算子/参数）
    """

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
        from .template_library import template_creation_strategy

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


# ---------------------------------------------------------------------------
# 4. 测试类型策略
# ---------------------------------------------------------------------------

@dataclass
class TestStrategyConfig(StrategyConfig):
    """测试策略配置."""

    name: str = "test"
    test_operators: Tuple[str, ...] = ("rank", "quantile", "winsorize")
    quantile_bins: Tuple[int, ...] = (5, 10, 20, 50)
    winsorize_limits: Tuple[float, ...] = (0.01, 0.05, 0.1)
    include_neutralize: bool = True


class TestStrategy(CreationStrategy):
    """测试类型策略 — 横截面算子测试因子信号.

    典型用途:
      - 测试原始信号的稳定性
      - 评估不同参数下的表现
      - 横截面标准化对比
    """

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


# ---------------------------------------------------------------------------
# 5. 策略组合
# ---------------------------------------------------------------------------

@dataclass
class CompositeConfig(StrategyConfig):
    """组合策略配置."""

    name: str = "composite"
    strategies: Tuple[str, ...] = ()  # ("multi_stage", "template")
    mode: str = "serial"  # serial | parallel


class CompositeStrategy(CreationStrategy):
    """组合策略 — 多策略串行/并行组合.

    串行模式:
      - 策略1的输出作为策略2的输入
      - 适用场景: first_order → unary_template

    并行模式:
      - 多策略独立执行，结果合并
      - 适用场景: template + test
    """

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

            # TODO: 如果需要，从tasks生成新的scalar_fields
            # current_fields = self._extract_fields_from_tasks(tasks)

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


# ---------------------------------------------------------------------------
# 策略工厂
# ---------------------------------------------------------------------------

def create_strategy(
    strategy_type: str,
    config: Optional[Union[Dict[str, Any], StrategyConfig]] = None,
    **kwargs
) -> CreationStrategy:
    """策略工厂 — 根据类型创建策略实例.

    Args:
        strategy_type: 策略类型
            - "multi_stage": 多阶工厂
            - "multivariate": 多元字段
            - "template": 模板库
            - "test": 测试类型
        config: 配置对象或字典
        **kwargs: 额外配置参数

    Returns:
        策略实例

    Examples:
        >>> strategy = create_strategy("template", {
        ...     "families": ("unary", "binary"),
        ...     "template_categories": ("analyst", "pv"),
        ... })
        >>> tasks = strategy.generate_tasks(scalar_fields, group_fields)
    """
    # 配置对象转换
    if isinstance(config, dict):
        config_map = {
            "multi_stage": MultiStageConfig,
            "multivariate": MultivariateConfig,
            "template": TemplateStrategyConfig,
            "test": TestStrategyConfig,
        }
        config_cls = config_map.get(strategy_type, StrategyConfig)
        config = config_cls(**{**config, **kwargs})

    # 策略实例化
    strategy_map = {
        "multi_stage": MultiStageStrategy,
        "multivariate": MultivariateStrategy,
        "template": TemplateStrategy,
        "test": TestStrategy,
    }

    strategy_cls = strategy_map.get(strategy_type)
    if not strategy_cls:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    return strategy_cls(config)


__all__ = [
    # 基类
    "CreationStrategy",
    "StrategyConfig",
    # 策略类
    "MultiStageStrategy",
    "MultivariateStrategy",
    "TemplateStrategy",
    "TestStrategy",
    "CompositeStrategy",
    # 配置类
    "MultiStageConfig",
    "MultivariateConfig",
    "TemplateStrategyConfig",
    "TestStrategyConfig",
    "CompositeConfig",
    # 工厂
    "create_strategy",
]