# 创建策略组件化架构

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Layer                               │
│  python alpha_machine.py survey --strategy template          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Orchestrator Layer                          │
│  orchestrator.py: _run_all() / survey()                     │
│  - 解析CLI参数                                              │
│  - 调用策略工厂                                             │
│  - 执行策略生成任务                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Strategy Factory Layer                      │
│  creation_strategy.py: create_strategy()                    │
│  - 根据策略类型创建实例                                      │
│  - 注入配置参数                                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
┌───────────────┐                 ┌───────────────┐
│   Concrete    │                 │   Composite   │
│   Strategies  │                 │   Strategy    │
└───────┬───────┘                 └───────┬───────┘
        │                                 │
        ├─ MultiStageStrategy             │ 组合多个策略
        ├─ TemplateStrategy               │ - serial: 串行执行
        ├─ TestStrategy                   │ - parallel: 并行执行
        ├─ MultivariateStrategy           │
        │                                 │
        └────────────────┬────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Layer                                │
│  - ScalarField (fields.py)                                  │
│  - Template (database/models.py)                            │
│  - AlphaDatabase (database/repository.py)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Output Layer                              │
│  - List[Task] (families.py)                                 │
│  - 每个Task包含:                                            │
│    * expression: 表达式                                      │
│    * template_index: 模板索引                                │
│    * family: 模板族                                          │
│    * decay: decay值                                          │
│    * meta: 元数据                                            │
└─────────────────────────────────────────────────────────────┘
```

## 策略类型对比

```
┌──────────────────┬──────────────────┬──────────────────┐
│  MultiStage      │   Template       │      Test        │
│  多阶工厂         │   模板库         │     测试类型      │
├──────────────────┼──────────────────┼──────────────────┤
│ first_order      │ placeholder      │ rank             │
│ + unary_template │ + fixed          │ quantile         │
│                  │                  │ winsorize        │
│                  │ 从数据库加载      │ neutralize       │
├──────────────────┼──────────────────┼──────────────────┤
│ 经典方法          │ 已验证模板        │ 信号稳定性测试    │
│ 快速基线          │ 按category过滤   │ 参数扫描          │
└──────────────────┴──────────────────┴──────────────────┘

┌──────────────────┬──────────────────┐
│  Multivariate    │    Composite     │
│  多元字段         │     组合策略      │
├──────────────────┼──────────────────┤
│ 多字段组合        │ 串行/并行组合    │
│ 跨category       │ 多策略融合        │
│ 复合因子          │ 灵活扩展         │
├──────────────────┼──────────────────┤
│ 创新探索          │ 复杂工作流        │
│ 因子融合          │ 最佳实践          │
└──────────────────┴──────────────────┘
```

## 数据流向

```
CLI参数
  │
  ├─ --strategy template
  ├─ --template-categories analyst pv
  └─ --decay 6.0
  │
  ▼
create_strategy("template", config)
  │
  ▼
TemplateStrategy.generate_tasks()
  │
  ├─ 从数据库加载模板
  │  SELECT * FROM template_library
  │  WHERE family IN ('unary', 'binary')
  │    AND active = 1
  │
  ├─ 按categories过滤字段
  │  scalar_fields.filter(category in template_categories)
  │
  ├─ 槽位分类与渲染
  │  - scalar槽: 标量字段组合
  │  - group槽: GROUP字段
  │  - fixed槽: 固定值
  │  - enum槽: 枚举值
  │
  └─ 组合展开
     combinations(scalar_fields, slot_count)
  │
  ▼
List[Task]
  │
  ├─ Task(expression="rank(close)", ...)
  ├─ Task(expression="ts_delta(volume, 5)", ...)
  └─ ...
  │
  ▼
提交到BRAIN平台进行回测
```

## 配置继承关系

```
StrategyConfig (基类)
  ├─ decay: float
  └─ name: str
      │
      ├─ MultiStageConfig
      │  ├─ include_first_order: bool
      │  ├─ include_unary_template: bool
      │  ├─ first_order_ops: Tuple[str, ...]
      │  └─ unary_template_indices: Tuple[int, ...]
      │
      ├─ TemplateStrategyConfig
      │  ├─ families: Tuple[str, ...]
      │  ├─ all_combinations: bool
      │  ├─ sample_n: int
      │  ├─ template_categories: Tuple[str, ...]
      │  └─ templates: Optional[Sequence[Template]]
      │
      ├─ TestStrategyConfig
      │  ├─ test_operators: Tuple[str, ...]
      │  ├─ quantile_bins: Tuple[int, ...]
      │  ├─ winsorize_limits: Tuple[float, ...]
      │  └─ include_neutralize: bool
      │
      ├─ MultivariateConfig
      │  ├─ min_fields: int
      │  ├─ max_fields: int
      │  ├─ combination_limit: int
      │  └─ cross_category: bool
      │
      └─ CompositeConfig
         ├─ strategies: Tuple[str, ...]
         └─ mode: str (serial | parallel)
```

## 扩展新策略

```
步骤1: 定义配置类
  ┌─────────────────────────────────┐
  │ @dataclass                      │
  │ class MyStrategyConfig(         │
  │     StrategyConfig              │
  │ ):                              │
  │     my_param: str = "default"   │
  └─────────────────────────────────┘

步骤2: 实现策略类
  ┌─────────────────────────────────┐
  │ class MyStrategy(               │
  │     CreationStrategy            │
  │ ):                              │
  │   def generate_tasks(           │
  │       self, fields, groups      │
  │   ) -> List[Task]:              │
  │       # 实现你的逻辑            │
  │       return tasks              │
  └─────────────────────────────────┘

步骤3: 注册到工厂
  ┌─────────────────────────────────┐
  │ strategy_map = {                │
  │   ...                           │
  │   "my_strategy": MyStrategy,    │
  │ }                               │
  └─────────────────────────────────┘
```

## 最佳实践

```
探索阶段 → template策略
  ├─ 从已验证模板开始
  ├─ 按category过滤字段
  └─ 快速生成baseline

优化阶段 → test策略
  ├─ 测试不同参数
  ├─ 评估稳定性
  └─ 找到最优配置

创新阶段 → multivariate策略
  ├─ 探索新组合
  ├─ 跨category融合
  └─ 发现新因子

基线对比 → multi_stage策略
  ├─ 经典一阶方法
  ├─ 快速baseline
  └─ 性能对比参考

复杂工作流 → composite策略
  ├─ 多策略组合
  ├─ 串行/并行执行
  └─ 最佳实践融合
```

这个架构设计提供了灵活、可扩展的策略系统，支持你提出的多阶工厂、多元字段、模板构建等不同流程的组件化实现。