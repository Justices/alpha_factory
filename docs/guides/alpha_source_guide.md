# Alpha获取与筛选完整流程

## 问题背景

用户提问：`filter_alphas_for_optimization(alphas, alpha_ids=["alpha_001", ...])` 中的 `alphas` 参数从哪里来？

**答案**: 需要先从某个来源获取alphas列表，然后再筛选。框架提供三种来源。

## 三种获取方式

### 方式1: 从工作流结果获取

```python
# 步骤1: 运行工作流
from alpha_operator_framework import run_full_workflow, FieldSpec

result = await run_full_workflow(
    region="EUR",
    universe="TOP2500",
    dataset_id="pv1",
    field_ids=["close", "volume"],
    execute=True  # 实际执行生成结果文件
)

# 步骤2: 从结果中提取alphas
from alpha_operator_framework import get_alphas_from_workflow_result

alphas = get_alphas_from_workflow_result(result, "survey")

# 步骤3: 筛选
from alpha_operator_framework import filter_high_quality_alphas

high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
```

### 方式2: 从文件读取

```python
# 步骤1: 运行工作流生成文件(仅第一次)
result = await run_full_workflow(..., execute=True)
# 文件保存在: runs/survey_results_EUR_pv1.json

# 步骤2: 后续直接从文件读取(无需重新运行)
from alpha_operator_framework import load_alphas_from_file

alphas = load_alphas_from_file("runs/survey_results_EUR_pv1.json")

# 步骤3: 筛选
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
```

### 方式3: 从平台查询

```python
# 方式A: 按条件查询
from alpha_operator_framework import fetch_user_alphas

alphas = await fetch_user_alphas(
    region="EUR",      # EUR市场
    status="IS",       # 未提交的alpha
    min_sharpe=1.2,    # Sharpe > 1.2
    limit=50           # 最多50个
)

# 方式B: 按alpha_id精确查询
from alpha_operator_framework import fetch_alpha_by_ids

alphas = await fetch_alpha_by_ids(["alpha_001", "alpha_002"])

# 然后筛选
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
```

## 一站式获取并筛选

```python
from alpha_operator_framework import get_and_filter_alphas

# 一步完成: 获取 + 筛选
filtered = await get_and_filter_alphas(
    source="platform",          # 来源
    region="EUR",                # 平台查询参数
    min_sharpe=1.58,             # 筛选条件
    limit=50
)
```

## 典型AI工作流

### 场景1: 用户指定alpha_id

```python
# 用户: "优化alpha_001, alpha_002, alpha_003"

# 方式A: 直接查询(需要alpha_machine)
alphas = await fetch_alpha_by_ids(["alpha_001", "alpha_002", "alpha_003"])

# 方式B: 如果已有结果文件
alphas = load_alphas_from_file("runs/survey_results.json")
filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002", "alpha_003"]
)

# AI回复
print(f"筛选出{len(filtered)}个alpha进行优化")
```

### 场景2: 用户按条件筛选

```python
# 用户: "找出sharpe>1.58, fitness>1.0的alpha"

# 从文件读取
alphas = load_alphas_from_file("runs/survey_results.json")

# 筛选
high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.03
)

# AI回复
print(f"找到{len(high_quality)}个高质量alpha")
for a in high_quality:
    print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f}")
```

### 场景3: 寻找优化机会

```python
# 用户: "哪些alpha有优化潜力?"

# 从工作流结果读取
alphas = get_alphas_from_workflow_result(result)

# 筛选边缘alpha(sharpe在1.2-1.8之间)
from alpha_operator_framework import filter_marginal_alphas

marginal = filter_marginal_alphas(
    alphas,
    sharpe_range=(1.2, 1.8),
    limit=20
)

# AI分析
print(f"发现{len(marginal)}个边缘alpha,有优化潜力")
for a in marginal:
    sharpe = a['sharpe']
    gap = 1.58 - sharpe
    print(f"  {a['alpha_id']}: sharpe={sharpe:.2f}, 需提升{gap:.2f}")
    if gap < 0.2:
        print(f"    建议: 调整decay参数")
    else:
        print(f"    建议: 尝试组合group操作")
```

## 完整流程图

```
┌─────────────────────────────────────────────────────────┐
│  用户需求: 筛选/优化alpha                                 │
└───────────────┬─────────────────────────────────────────┘
                │
        ┌───────▼────────┐
        │  从哪里获取?   │
        └───────┬────────┘
                │
    ┌───────────┼───────────┬───────────────┐
    │           │           │               │
┌───▼───┐   ┌───▼───┐   ┌───▼───┐   ┌──────▼─────┐
│工作流  │   │ 文件  │   │ 平台  │   │一站式调用  │
│结果    │   │ 读取  │   │ 查询  │   │(get_and_   │
│        │   │       │   │       │   │filter)    │
└───┬───┘   └───┬───┘   └───┬───┘   └──────┬─────┘
    │           │           │              │
    │           │           │              │
    └───────────┴───────────┴──────────────┘
                │
                │  获取alphas列表
                │
        ┌───────▼────────┐
        │  筛选alpha     │
        │  (按id或条件)  │
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │  提供优化建议  │
        └────────────────┘
```

## API速查表

### 获取alphas

```python
# 从工作流结果
alphas = get_alphas_from_workflow_result(result, "survey")

# 从文件
alphas = load_alphas_from_file("path/to/file.json")

# 从平台(条件查询)
alphas = await fetch_user_alphas(region="EUR", min_sharpe=1.2, limit=50)

# 从平台(精确查询)
alphas = await fetch_alpha_by_ids(["alpha_001", "alpha_002"])

# 一站式
alphas = await get_and_filter_alphas(source="platform", region="EUR", min_sharpe=1.58)
```

### 筛选alphas

```python
# 指定alpha_id
filtered = filter_alphas_for_optimization(alphas, alpha_ids=["alpha_001"])

# 高质量
filtered = filter_high_quality_alphas(alphas, min_sharpe=1.58)

# 边缘alpha
filtered = filter_marginal_alphas(alphas, sharpe_range=(1.2, 1.8))

# 可提交
filtered = filter_ready_for_submission(alphas)

# 通用筛选
from alpha_operator_framework.optimize import AlphaFilter, filter_alphas
config = AlphaFilter(min_sharpe=1.58, region="EUR", limit=10)
filtered = filter_alphas(alphas, config)
```

## 示例代码

完整示例见: `examples/alpha_source_examples.py`

```bash
python3 examples/alpha_source_examples.py
```

## 总结

- ✅ `alphas`参数需要先获取
- ✅ 三种来源: 工作流/文件/平台
- ✅ 提供便捷函数获取
- ✅ 支持一站式获取+筛选
- ✅ AI可根据场景选择合适的方式

**推荐流程**: 运行survey → 保存结果 → 从文件读取 → 筛选 → 优化建议