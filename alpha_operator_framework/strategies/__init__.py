"""创建策略模块.

策略类型:
  1. MultiStageStrategy: 多阶工厂 (first_order + unary_template)
  2. MultivariateStrategy: 多元字段构建
  3. TemplateStrategy: 模板库构建
  4. TestStrategy: 测试类型 (横截面算子 rank/quantile/winsorize)
  5. CompositeStrategy: 组合策略 (串行/并行)

设计原则:
  * 策略可插拔: 通过配置切换
  * 策略可组合: 多策略串行/并行
  * 策略可配置: 每个策略有独立配置
  * 统一输出: 都返回 List[Task]
"""

from .base import CreationStrategy, StrategyConfig
from .multi_stage import MultiStageConfig, MultiStageStrategy
from .multivariate import MultivariateConfig, MultivariateStrategy
from .template import TemplateStrategy, TemplateStrategyConfig
from .test import TestStrategy, TestStrategyConfig
from .composite import CompositeConfig, CompositeStrategy

from typing import Any, Dict, Optional, Union


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