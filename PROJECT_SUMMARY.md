# Alpha Operator Framework 项目总结

## 项目背景

### 原始项目
1. **machine_lib.py** (位于 `/Users/liujiaping/ai/quant/scripts/`)
   - 多阶因子生成库
   - 支持一阶因子(basic_ops, ts_ops)、二阶因子(group_ops)
   - 提供批量模拟和提交功能

2. **cold_templates** (位于 `/Users/liujiaping/ai/quant/scripts/cold_templates/`)
   - 冷神模板群项目(基于论坛帖子35253150989719)
   - 结构正交的一元/二元/三元模板
   - 因子密度评估方法论

### 整合动机
- **machine_lib**: 表达式复杂度高,但缺乏系统化的筛选方法论
- **cold_templates**: 有系统的密度评估方法,但表达式固定,灵活性较低
- **整合目标**: 将多阶因子生成能力与结构正交模板方法论结合

## 项目结构

```
/Users/liujiaping/ai/template_project/
├── README.md                           # 项目说明
├── alpha_operator_framework/           # 核心包
│   ├── __init__.py                    # 包入口
│   ├── operators.py                   # 算子库(来自machine_lib)
│   ├── families.py                    # 模板族(扩展自cold_templates)
│   ├── fields.py                      # 字段处理(整合两者)
│   ├── density.py                     # 密度评估(来自cold_templates)
│   └── orchestrator.py                # 三段工作流
├── examples/                           # 示例脚本
│   └── demo_workflow.py               # 完整演示
├── tests/                              # 单元测试
│   └── test_framework.py              # 测试套件
└── runs/                               # 输出目录
    └── .gitkeep
```

## 核心模块说明

### 1. operators.py - 算子库
**来源**: machine_lib.py

**核心内容**:
```python
# 算子分类
basic_ops = ["reverse", "rank", "zscore", ...]      # 基础变换
ts_ops = ["ts_rank", "ts_delta", "ts_sum", ...]    # 时间序列
group_ops = ["group_neutralize", "group_rank", ...] # 分组操作
extended_ops = ["regression_neut", ...]            # 扩展算子

# 工厂函数
ts_factory(op, field, windows)                     # ts算子生成
group_factory(op, field, region, ...)              # group算子生成
first_order_factory(fields, ops_set)               # 一阶因子工厂
second_order_factory(first_order_fields, ...)      # 二阶因子工厂
```

**新增功能**:
- 算子元数据管理(ACCESS_LIMITED_OPS)
- 统一的工厂接口

### 2. families.py - 模板族
**来源**: cold_templates/families.py

**核心内容**:
```python
# 三类模板
UNARY_TEMPLATES = (10个)     # 单字段操作
BINARY_TEMPLATES = (8个)     # 两字段回归/正交
TERNARY_TEMPLATES = (7个)    # 三字段联合/条件切换
QUATERNARY_TEMPLATES = (5个) # 新增: 多阶group模板

# 工厂函数
unary_factory(scalar_fields)           # 一元任务生成
binary_factory(scalar_fields)          # 二元任务生成
ternary_factory(scalar_fields)         # 三元任务生成
quaternary_factory(scalar_fields, group_fields)  # 四元任务生成
```

**新增功能**:
- QUATERNARY_TEMPLATES: 整合machine_lib的group_ops作为第四元素
- 扩展模板支持多阶组合

### 3. fields.py - 字段处理
**来源**: 整合machine_lib.process_datafields与cold_templates.fields_pool

**核心内容**:
```python
# 数据结构
FieldSpec(id, dataset_id, type, coverage, ...)  # 字段规格

# 预处理
preprocess_field(field, ...)                     # 单字段预处理
sample_scalar_expressions(fields, spec)          # 字段池采样

# 组合采样
sample_pair_combinations(fields, spec)           # 二元采样
sample_triple_combinations(fields, spec)         # 三元采样
```

**整合策略**:
- 保留machine_lib的预处理逻辑(winsorize + ts_backfill)
- 继承cold_templates的采样方法论(随机80组合)

### 4. density.py - 密度评估
**来源**: cold_templates/density.py

**核心内容**:
```python
# 信号门定义
SignalGate(abs_sharpe_min=0.7, abs_fitness_min=0.7, ...)

# 密度计算
compute_density(results, gate)                   # 按模板聚合密度
top_templates(density_rows, top_n=3)            # 取top-N模板
```

**设计红线**:
- 纯函数,无网络访问
- 可复现的评估逻辑

### 5. orchestrator.py - 三段工作流
**来源**: 扩展自cold_templates/orchestrator.py

**核心流程**:
```bash
# Survey阶段
survey --region EUR --universe TOP2500 --sample 80 --execute
  ↓ 字段池采样 × 全模板族
  ↓ 密度评估 → top-3模板

# Deepen阶段
deepen --density-out runs/survey_density.json --sample 400 --execute
  ↓ top-3模板 × 全字段
  ↓ 质量门筛选 → 候选列表

# Submit阶段
submit --kept-out runs/deepen_kept.json --execute
  ↓ 列出候选
  ↓ (可选) 触发check
```

**设计红线**:
- 默认dry-run,需显式--execute才消耗额度
- 会话单管理(经alpha_machine.simulate)
- 零授权submit

## 整合创新点

### 1. 模板层扩展
- **cold_templates**: 固定的一元/二元/三元模板
- **整合后**: 新增四元模板,支持多阶group操作

### 2. 字段层增强
- **cold_templates**: 原始字段直接作为模板输入
- **整合后**: 支持machine_lib的多阶预处理(一阶→二阶group→模板输入)

### 3. 算子层统一
- **machine_lib**: 散落在各处的算子定义
- **整合后**: 统一的算子库管理,支持元数据(ACCESS_LIMITED_OPS)

### 4. 工作流标准化
- **machine_lib**: 脚本式调用
- **整合后**: CLI标准化的三段工作流(survey→deepen→submit)

## 使用示例

### 快速开始
```bash
# 1. 运行演示(不消耗额度)
python3 examples/demo_workflow.py

# 2. 运行单元测试
python3 tests/test_framework.py
```

### 完整工作流
```bash
# 1. Survey: 调研EUR市场
python3 -m alpha_operator_framework.orchestrator survey \
  --region EUR --universe TOP2500 \
  --sample 80 --execute

# 2. Deepen: 深挖top-3模板
python3 -m alpha_operator_framework.orchestrator deepen \
  --density-out runs/survey_density.json \
  --sample 400 --execute

# 3. Submit: 列出候选
python3 -m alpha_operator_framework.orchestrator submit \
  --kept-out runs/deepen_kept.json

# 4. (可选) 触发check
python3 -m alpha_operator_framework.orchestrator submit \
  --kept-out runs/deepen_kept.json --execute
```

### Python API
```python
from alpha_operator_framework import (
    # 模板族
    unary_factory, binary_factory,
    # 算子
    basic_ops, ts_factory,
    # 字段
    FieldSpec, sample_scalar_expressions,
    # 密度
    compute_density, top_templates,
)

# 1. 字段预处理
fields = [FieldSpec(id="close", dataset_id="pv1", type="MATRIX", ...)]
scalars = sample_scalar_expressions(fields, SampleSpec(sample_n=80))

# 2. 任务生成
tasks = unary_factory(scalars)

# 3. 模拟(需配置alpha_machine)
# results = await alpha_machine.simulate([t.to_sim_dict() for t in tasks], ...)

# 4. 密度评估
density_rows = compute_density(results)
top3 = top_templates(density_rows, top_n=3)
```

## 后续扩展方向

### 1. 算子扩展
- 新增更多时间序列算子(ts_moment, ts_entropy等)
- 支持自定义算子注册

### 2. 模板扩展
- 支持用户自定义模板
- 模板版本管理

### 3. 平台集成
- 深度集成alpha_machine API
- 支持更多region/universe组合

### 4. 可视化
- 密度报告可视化dashboard
- 模板性能对比图表

## 测试与验证

### 单元测试
```bash
$ python3 tests/test_framework.py

测试算子库...
✓ 算子库测试通过
测试模板族...
✓ 模板族测试通过
测试字段处理...
✓ 字段处理测试通过
测试密度评估...
✓ 密度评估测试通过

✓ 所有测试通过!
```

### 演示运行
```bash
$ python3 examples/demo_workflow.py

一元模板: 10 个
二元模板: 8 个
三元模板: 7 个

基础算子: ['reverse', 'inverse', 'rank', ...]
时间序列算子: ['ts_rank', 'ts_zscore', 'ts_delta', ...]
分组算子: ['group_neutralize', 'group_rank', 'group_zscore']

✓ 演示完成!
```

## 许可与引用

本框架整合自:
- **machine_lib.py**: 多阶因子生成方法论
- **cold_templates**: 冷神模板群方法论(论坛帖子35253150989719)

如需引用,请注明原始来源。