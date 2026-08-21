# 创建策略组件化改进总结

## 问题背景

原有的 `TemplateStrategyConfig` 只是一个简单的配置类，无法满足多样化的构建需求：
- 多阶工厂（first_order + unary_template）
- 模板库构建（从数据库提炼）
- 测试类型（横截面算子）
- 多元字段构建

## 解决方案

采用**策略模式**，将不同的构建逻辑抽象为可插拔的策略组件。

### 架构设计

```
CreationStrategy (抽象基类)
    ├── MultiStageStrategy     # 多阶工厂
    ├── TemplateStrategy        # 模板库
    ├── TestStrategy            # 测试类型
    ├── MultivariateStrategy    # 多元字段
    └── CompositeStrategy       # 组合策略
```

### 核心文件

1. **`alpha_operator_framework/creation_strategy.py`** (新增)
   - 定义策略抽象基类 `CreationStrategy`
   - 实现5种具体策略类
   - 提供策略工厂 `create_strategy()`

2. **`alpha_operator_framework/orchestrator.py`** (修改)
   - 集成策略工厂
   - 添加CLI参数 `--strategy`
   - 支持策略动态切换

3. **`docs/strategy_usage.md`** (新增)
   - 完整的使用指南
   - 配置参数说明
   - 最佳实践建议

## 关键特性

### 1. 统一接口

所有策略都遵循统一的接口：

```python
strategy.generate_tasks(scalar_fields, group_fields, **kwargs) -> List[Task]
```

### 2. 策略可插拔

通过配置切换策略：

```bash
# CLI方式
python alpha_machine.py survey --strategy template --template-categories analyst

# Python方式
strategy = create_strategy("template", {"template_categories": ("analyst",)})
tasks = strategy.generate_tasks(scalar_fields)
```

### 3. 策略可组合

支持串行和并行组合：

```python
# 并行组合: template + test
strategies = [
    create_strategy("template"),
    create_strategy("test"),
]
composite = CompositeStrategy(strategies, CompositeConfig(mode="parallel"))

# 串行组合: first_order → unary
strategies = [
    create_strategy("multi_stage", {"include_first_order": True}),
    create_strategy("multi_stage", {"include_unary_template": True}),
]
composite = CompositeStrategy(strategies, CompositeConfig(mode="serial"))
```

### 4. 易扩展

新增策略只需3步：
1. 定义配置类（继承 `StrategyConfig`）
2. 实现策略类（继承 `CreationStrategy`）
3. 注册到工厂（修改 `create_strategy()`）

## 使用示例

### 模板库策略（默认）

```bash
python alpha_machine.py survey --strategy template \
    --template-categories analyst pv
```

### 多阶工厂策略

```bash
python alpha_machine.py survey --strategy multi_stage
```

### 测试策略

```bash
python alpha_machine.py survey --strategy test \
    --test-operators rank quantile winsorize
```

### 组合策略

```bash
python alpha_machine.py survey --strategy composite
```

## 与原有代码的兼容性

### 向后兼容

- `--template-library` 参数保留，映射到 `--strategy template`
- `--no-template-library` 参数保留，映射到 `--strategy multi_stage`
- 原有的 `template_creation_strategy()` 函数保留，由 `TemplateStrategy` 内部调用

### 数据库兼容

- 模板库表结构不变
- Template 数据模型不变
- 槽位渲染逻辑复用现有实现

## 测试验证

运行测试：

```bash
python3 tests/test_creation_strategy.py
```

测试结果：

```
[1] 多阶工厂策略: 生成39个任务
[2] 模板库策略: 需要数据库模板库
[3] 测试策略: 生成15个任务（rank/quantile/neutralize）
[4] 多元字段策略: 生成组合任务
[5] 组合策略: 并行组合多个策略
```

## 后续优化建议

### 1. 策略配置持久化

将策略配置保存到数据库，支持配置复用：

```python
# 保存策略配置
db.save_strategy_config("my_template", {
    "strategy_type": "template",
    "template_categories": ("analyst", "pv"),
})

# 加载策略配置
config = db.load_strategy_config("my_template")
strategy = create_strategy(**config)
```

### 2. 策略性能监控

为每个策略添加性能指标：

```python
strategy = create_strategy("template")
tasks = strategy.generate_tasks(fields)

print(f"生成任务数: {len(tasks)}")
print(f"耗时: {strategy.last_execution_time:.2f}s")
print(f"字段匹配率: {strategy.field_match_rate:.2%}")
```

### 3. 策略智能推荐

根据历史数据推荐最优策略：

```python
# 根据历史提交成功率推荐策略
recommended = db.recommend_strategy(
    categories=("analyst",),
    target_sharpe=1.5,
)

strategy = create_strategy(recommended["strategy_type"], recommended["config"])
```

### 4. 策略可视化

添加策略流程可视化：

```python
from alpha_operator_framework.visualization import plot_strategy_flow

strategy = create_strategy("composite")
plot_strategy_flow(strategy, output="strategy_flow.html")
```

## 总结

这次改进实现了：

1. ✅ **组件化**: 将构建逻辑抽象为可插拔的策略组件
2. ✅ **统一接口**: 所有策略遵循 `CreationStrategy` 抽象
3. ✅ **灵活组合**: 支持策略的串行/并行组合
4. ✅ **易于扩展**: 新增策略只需实现统一接口
5. ✅ **向后兼容**: 保留原有参数和接口

这为后续的多阶工厂、多元字段、模板构建等不同流程提供了灵活的架构支持，符合你提出的组件化设计目标。