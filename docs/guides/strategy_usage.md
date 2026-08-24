# 因子生成策略组件化使用指南 (Strategy Usage Guide)

> **定位**: 详细介绍 `alpha_operator_framework/generation/` 策略组件、10 大生成族群、AST 杂交生成与多策略组合的使用方式。

---

## 一、 策略体系概述

框架提供了高内聚、易扩展的任务生成策略组件：
- **`template`**: 基于预置与数据库沉淀模板库生成任务（支持按 family / category 过滤）；
- **`multi_stage`**: 多阶工厂策略（一阶时序展开 + 一元/二元模板包装）；
- **`symbolic_evolution`**: 基于 `SymbolicTreeBreeder` 的递归 AST 语法自由杂交生成；
- **`distilled`**: 消费通过 `TemplateAbstractor` 反向蒸馏回填的胜出骨架；
- **`composite`**: 多策略串行/并行组合。

---

## 二、 核心 API 与使用范式

### 1. 模板库策略 (`TemplateCreationStrategy`)

```python
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation import create_strategy

# 1. 创建策略实例
strategy = create_strategy("template", {
    "families": ("unary", "binary", "distilled"),
    "template_categories": ("analyst", "fundamental", "pv"),
    "decay": 12.0,
})

# 2. 传入字段生成候选任务
fields = [
    FieldSpec(id="returns", dataset_id="pv1", type="MATRIX"),
    FieldSpec(id="volume", dataset_id="pv1", type="MATRIX"),
    FieldSpec(id="market_cap", dataset_id="pv1", type="MATRIX"),
]
tasks = strategy.generate_tasks(fields, group_fields=["subindustry", "sector"])
print(f"✅ 成功生成 {len(tasks)} 个模板任务")
for t in tasks[:3]:
    print(f"   • {t.expression}")
```

### 2. 多阶工厂策略 (`MultiStageCreationStrategy`)

先应用一阶算子（`ts_rank`, `ts_delta`, `ts_zscore` 等），再包装二阶行业中性化或截面算子：

```python
strategy = create_strategy("multi_stage", {
    "include_first_order": True,
    "include_unary_template": True,
    "first_order_ops": ("ts_rank", "ts_delta", "ts_zscore"),
    "decay": 12.0,
})

tasks = strategy.generate_tasks(fields)
```

### 3. 递归 AST 符号自由杂交 (`SymbolicTreeBreeder`)

无需手写固定公式模板，自动递归生成 1~4 层深度的现代量化高阶形态（如三层架构与特质正交分解）：

```python
from alpha_operator_framework.domain.ast.breeder import SymbolicTreeBreeder

breeder = SymbolicTreeBreeder(max_depth=3)
generated_exprs = breeder.breed(fields, count=20)
for expr in generated_exprs[:5]:
    print(f"   • {expr}")
```

---

## 三、 CLI 命令行调用范式

```bash
# 1. 分层地毯式挖掘 (并行调度 10 大生成族群)
python alpha_machine.py mine \
    --region GBR --universe TOP700 \
    --datasets "insider_agg_matrix,pattern_scores" \
    --sample-per-family 4 --batch-size 5 \
    --execute

# 2. 全新 DDD 投研生命周期 (指定抽样探索算法)
python alpha_machine.py research-cycle \
    --region GBR --universe TOP700 \
    --algorithm d_optimal --sample-per-family 4 \
    --execute
```