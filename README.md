# Alpha Factor Operator Framework

整合 `machine_lib.py` 多阶因子生成能力与 `cold_templates` 结构正交模板方法论，构建系统化的alpha因子研究框架。

**专为AI集成优化**: 支持精确参数控制、结构化结果、单次API调用完整工作流。

## 快速开始

### Python API (AI推荐方式)

```python
from alpha_operator_framework import run_full_workflow, FieldSpec

# AI指定精确参数: 区域/宇宙/数据集/字段列表
result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    field_ids=["close", "volume", "returns"],  # 精确字段列表
    execute=False  # Dry-run先查看任务
)

# AI解析结构化结果
if result["survey"].success:
    print(f"生成{result['survey'].tasks_generated}个任务")
    for t in result["survey"].top_templates:
        print(f"  [{t['family']}/{t['template_index']}] density={t['density']:.2f}")
```

### 运行示例

```bash
# 演示工作流
python3 examples/demo_workflow.py

# AI工作流示例
python3 examples/ai_workflow_examples.py
```

### 使用本地字段文件预筛选

字段文件支持平台导出的 CSV，以及字段对象组成的 JSON 数组。提供本地文件后，
Survey 不会请求平台字段接口；会按 `region`、`universe`、`delay`、`dataset`、
`type` 和 `search` 过滤，再按 coverage 和冷门度进入后续预筛选。

```bash
python3 -m alpha_operator_framework.orchestrator survey \
  --fields-file /path/to/fields.csv \
  --region GBR --universe TOP700 --delay 1 \
  --min-coverage 0.1 --sample 80 --backtest-sample 100
```

Python API：

```python
results = await run_full_workflow(
    region="GBR",
    universe="TOP700",
    delay=1,
    fields_file="/path/to/fields.json",
    execute=False,
)
```

### 语义二元配对

Survey 会在实际入选字段中自动识别同数据集的定向字段对，并将表达式与一阶
表达式一起登记、随机抽样回测：

- `earnings_positive` + `earnings_negative` → `positive - negative`
- `abc_revenue` + `abc_cap` → `abc_revenue / abc_cap`

`*_cap` 只会匹配同数据集、同前缀的字段，避免无关字段相除。需要关闭时传入
`--no-semantic-pairs`。

## 核心特性

### 1. AI友好的API设计
- **精确参数控制**: 指定区域、宇宙、数据集、字段列表
- **结构化结果**: Python对象而非文本，便于解析
- **单次调用**: `run_full_workflow()` 完成survey→deepen→submit
- **Dry-run优先**: 默认不消耗额度，AI可先查看再决策

### 2. 整合创新
- **模板层扩展**: 新增四元模板，支持多阶group操作
- **算子层统一**: 统一管理basic_ops/ts_ops/group_ops
- **字段层增强**: 多阶预处理+精确指定
- **工作流标准化**: 三段方法论(survey→deepen→submit)

### 3. 灵活的字段选择

**方式1: 指定精确字段**
```python
result = await run_full_workflow(
    field_ids=["close", "volume", "returns"]
)
```

**方式2: 数据集+采样**
```python
result = await run_full_workflow(
    dataset_id="pv1",
    sample_n=80
)
```

**方式3: 全字段**
```python
result = await run_full_workflow(
    dataset_id="",  # 空=全字段
    sample_n=80
)
```

### 4. Alpha筛选与优化

支持两种筛选方式:

**方式A: 指定alpha_id**
```python
# 精确筛选
filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002", "alpha_003"]
)
```

**方式B: 按回测指标**
```python
# 高质量alpha: sharpe>1.58, fitness>1.0
high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.03
)

# 边缘alpha(有优化潜力): sharpe在1.2-1.8之间
marginal = filter_marginal_alphas(
    alphas,
    sharpe_range=(1.2, 1.8),
    limit=20
)

# 可提交的alpha
ready = filter_ready_for_submission(alphas)
```

**AI决策示例**:
```python
# AI自动分析
marginal = filter_marginal_alphas(alphas)

if len(marginal) > 0:
    print(f"发现{len(marginal)}个边缘alpha可优化")
    for a in marginal:
        print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f}")
        print(f"    建议: 调整decay参数或组合group操作")
```

## 与原项目的关系

- 继承 `machine_lib.py` 的核心算子和多阶组合逻辑
- 继承 `cold_templates` 的模板族定义和密度评估方法论
- 新增：算子元数据、模板扩展机制、统一接口

## 设计红线

1. **纯函数优先**: families/operators/density模块无网络访问
2. **会话单管理**: 模拟统一经`alpha_machine.simulate`（brain_client）
3. **零授权submit**: 默认dry-run，需显式`--execute`才触发check
4. **区域自适应**: group操作符按region自动匹配可用GROUP字段
