# 创建策略组件化使用指南

## 概述

`creation_strategy.py` 实现了组件化的任务生成策略，支持多种构建方式的灵活组合：

- **multi_stage**: 多阶工厂（first_order + unary_template）
- **template**: 模板库构建（从数据库中提炼的模板）
- **test**: 测试类型（横截面算子 rank/quantile/winsorize）
- **multivariate**: 多元字段构建
- **composite**: 组合策略（多策略串行/并行）

## 架构设计

### 1. 策略抽象基类

所有策略都继承自 `CreationStrategy`，统一接口：

```python
class CreationStrategy(ABC):
    @abstractmethod
    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        pass
```

### 2. 策略工厂

通过工厂函数创建策略实例：

```python
strategy = create_strategy("template", {
    "families": ("unary", "binary"),
    "template_categories": ("analyst", "pv"),
})
tasks = strategy.generate_tasks(scalar_fields, group_fields)
```

## 使用示例

### 1. 模板库策略（默认）

从数据库模板库生成任务，支持按categories过滤：

```bash
# 使用模板库策略（默认）
python alpha_machine.py survey --strategy template \
    --template-categories analyst pv \
    --all-combinations

# 配置参数
python alpha_machine.py run-all --strategy template \
    --template-categories analyst \
    --sample 100 \
    --decay 6.0
```

Python代码：

```python
from alpha_operator_framework.creation_strategy import create_strategy

strategy = create_strategy("template", {
    "families": ("unary", "binary", "ternary"),
    "template_categories": ("analyst", "pv"),
    "all_combinations": True,
    "decay": 6.0,
})

tasks = strategy.generate_tasks(scalar_fields, group_fields=["sector"])
```

### 2. 多阶工厂策略

先应用一阶算子（rank/zscore等），再应用unary模板：

```bash
# 使用多阶策略
python alpha_machine.py survey --strategy multi_stage

# 配置一阶算子
python alpha_machine.py run-all --strategy multi_stage \
    --first-order-ops rank zscore normalize
```

Python代码：

```python
strategy = create_strategy("multi_stage", {
    "include_first_order": True,
    "include_unary_template": True,
    "first_order_ops": ("rank", "zscore", "scale", "winsorize"),
    "decay": 6.0,
})

tasks = strategy.generate_tasks(scalar_fields)
```

### 3. 测试策略

使用横截面算子测试因子信号的稳定性：

```bash
# 测试策略
python alpha_machine.py survey --strategy test \
    --test-operators rank quantile winsorize

# 配置参数
python alpha_machine.py run-all --strategy test \
    --test-operators rank quantile \
    --quantile-bins 5 10 20
```

Python代码：

```python
strategy = create_strategy("test", {
    "test_operators": ("rank", "quantile", "winsorize"),
    "quantile_bins": (5, 10, 20),
    "winsorize_limits": (0.01, 0.05),
    "include_neutralize": True,
    "decay": 6.0,
})

tasks = strategy.generate_tasks(scalar_fields, group_fields=["sector"])
```

### 4. 多元字段策略

构建多字段组合的复合因子：

```bash
# 多元字段策略
python alpha_machine.py survey --strategy multivariate \
    --min-fields 2 --max-fields 5

# 跨category组合
python alpha_machine.py run-all --strategy multivariate \
    --cross-category \
    --combination-limit 1000
```

Python代码：

```python
strategy = create_strategy("multivariate", {
    "min_fields": 2,
    "max_fields": 5,
    "cross_category": True,
    "combination_limit": 1000,
    "decay": 6.0,
})

tasks = strategy.generate_tasks(scalar_fields)
```

### 5. 组合策略（高级）

组合多个策略，串行或并行执行：

```python
from alpha_operator_framework.creation_strategy import (
    create_strategy,
    CompositeStrategy,
    CompositeConfig,
)

# 并行组合: template + test
strategies = [
    create_strategy("template", {"template_categories": ("analyst",)}),
    create_strategy("test", {"test_operators": ("rank", "quantile")}),
]

composite = CompositeStrategy(strategies, CompositeConfig(
    mode="parallel",  # 或 "serial"
))

tasks = composite.generate_tasks(scalar_fields, group_fields)

# 串行组合: first_order → unary_template
strategies = [
    create_strategy("multi_stage", {"include_first_order": True, "include_unary_template": False}),
    create_strategy("multi_stage", {"include_first_order": False, "include_unary_template": True}),
]

composite = CompositeStrategy(strategies, CompositeConfig(mode="serial"))
tasks = composite.generate_tasks(scalar_fields)
```

CLI使用：

```bash
# 组合策略
python alpha_machine.py survey --strategy composite
```

## 配置参数说明

### TemplateStrategyConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `families` | Tuple[str, ...] | ("unary", "binary", "ternary", "quaternary") | 使用的模板族 |
| `all_combinations` | bool | True | 是否生成所有组合 |
| `sample_n` | int | 80 | 非全组合时的采样上限 |
| `template_categories` | Tuple[str, ...] | () | 模板/字段category过滤 |
| `decay` | float | 6.0 | decay值 |

### MultiStageConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `include_first_order` | bool | True | 是否包含一阶算子 |
| `include_unary_template` | bool | True | 是否包含unary模板 |
| `first_order_ops` | Tuple[str, ...] | ("rank", "zscore", ...) | 一阶算子集合 |
| `decay` | float | 6.0 | decay值 |

### TestStrategyConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `test_operators` | Tuple[str, ...] | ("rank", "quantile", "winsorize") | 测试算子 |
| `quantile_bins` | Tuple[int, ...] | (5, 10, 20, 50) | quantile分箱数 |
| `winsorize_limits` | Tuple[float, ...] | (0.01, 0.05, 0.1) | winsorize限制 |
| `include_neutralize` | bool | True | 是否包含中性化测试 |

### MultivariateConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_fields` | int | 2 | 最小字段数 |
| `max_fields` | int | 5 | 最大字段数 |
| `combination_limit` | int | 1000 | 组合上限 |
| `cross_category` | bool | False | 是否跨category组合 |

## 扩展新策略

### 步骤1: 定义配置类

```python
@dataclass
class MyStrategyConfig(StrategyConfig):
    name: str = "my_strategy"
    my_param: str = "default_value"
```

### 步骤2: 实现策略类

```python
class MyStrategy(CreationStrategy):
    def __init__(self, config: Optional[MyStrategyConfig] = None):
        self.config = config or MyStrategyConfig()

    @property
    def name(self) -> str:
        return "my_strategy"

    def generate_tasks(
        self,
        scalar_fields: Sequence[ScalarField],
        group_fields: Optional[Sequence[str]] = None,
        **kwargs
    ) -> List[Task]:
        # 实现你的逻辑
        tasks = []
        for sf in scalar_fields:
            task = Task(
                expression=f"rank({sf.expr})",
                template_index=0,
                family="my_strategy",
                fields_per_alpha=1,
                decay=self.config.decay,
            )
            tasks.append(task)
        return tasks
```

### 步骤3: 注册到工厂

修改 `create_strategy()` 函数：

```python
def create_strategy(strategy_type: str, config: Optional[Union[Dict, StrategyConfig]] = None):
    # ...
    strategy_map = {
        "multi_stage": MultiStageStrategy,
        "multivariate": MultivariateStrategy,
        "template": TemplateStrategy,
        "test": TestStrategy,
        "my_strategy": MyStrategy,  # 新增
    }
    # ...
```

## 最佳实践

### 1. 策略选择建议

- **探索阶段**: 使用 `template` 策略，从已验证的模板库开始
- **优化阶段**: 使用 `test` 策略，测试不同参数下的表现
- **创新阶段**: 使用 `multivariate` 策略，探索新的字段组合
- **基线对比**: 使用 `multi_stage` 策略，与经典一阶方法对比

### 2. 组合策略建议

```python
# 推荐组合1: template + test
strategies = [
    create_strategy("template", {"template_categories": ("analyst",)}),
    create_strategy("test", {"test_operators": ("rank", "quantile")}),
]

# 推荐组合2: multi_stage + multivariate
strategies = [
    create_strategy("multi_stage"),
    create_strategy("multivariate", {"cross_category": True}),
]
```

### 3. 性能优化

- 使用 `sample_n` 限制组合数量
- 使用 `template_categories` 过滤无关字段
- 使用 `combination_limit` 控制多元组合上限

## 迁移指南

### 从旧 factory 迁移

```bash
# 旧方式
python alpha_machine.py survey --no-template-library

# 新方式（等价）
python alpha_machine.py survey --strategy multi_stage
```

### 从 template_library 迁移

```bash
# 旧方式
python alpha_machine.py survey --template-library --template-categories analyst

# 新方式（等价）
python alpha_machine.py survey --strategy template --template-categories analyst
```

## 总结

组件化策略系统提供了灵活、可扩展的任务生成方式：

1. **统一接口**: 所有策略都遵循 `CreationStrategy` 抽象
2. **可插拔**: 通过配置切换不同策略
3. **可组合**: 支持策略的串行/并行组合
4. **易扩展**: 新增策略只需实现统一接口

根据你的研究目标，选择合适的策略或组合，提高alpha研究的效率和效果。