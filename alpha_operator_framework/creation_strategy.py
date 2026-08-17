"""创建策略 — 代理导入策略模块.

策略已拆分到 strategies/ 子目录:
  - base.py: 基类定义
  - multi_stage.py: 多阶工厂策略
  - multivariate.py: 多元字段策略
  - template.py: 模板库策略
  - test.py: 测试类型策略
  - composite.py: 组合策略

此文件保持向后兼容，从 strategies/ 导入所有符号。
"""

from .strategies import (
    # 基类
    CreationStrategy,
    StrategyConfig,
    # 策略类
    MultiStageStrategy,
    MultivariateStrategy,
    TemplateStrategy,
    TestStrategy,
    CompositeStrategy,
    # 配置类
    MultiStageConfig,
    MultivariateConfig,
    TemplateStrategyConfig,
    TestStrategyConfig,
    CompositeConfig,
    # 工厂
    create_strategy,
)

__all__ = [
    "CreationStrategy",
    "StrategyConfig",
    "MultiStageStrategy",
    "MultivariateStrategy",
    "TemplateStrategy",
    "TestStrategy",
    "CompositeStrategy",
    "MultiStageConfig",
    "MultivariateConfig",
    "TemplateStrategyConfig",
    "TestStrategyConfig",
    "CompositeConfig",
    "create_strategy",
]