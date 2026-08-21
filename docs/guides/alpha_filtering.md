# Alpha筛选与优化功能

## 功能概述

新增 `optimize.py` 模块，支持灵活的alpha筛选：

1. **精确筛选**: 按alpha_id列表
2. **条件筛选**: 按回测指标范围(sharpe/fitness/turnover等)
3. **便捷函数**: 预定义的筛选场景(高质量/边缘/可提交)
4. **统计报告**: 筛选结果分析

## 核心API

### 1. filter_alphas_for_optimization - 通用筛选

**用途**: 支持精确和条件两种筛选方式

**参数**:
```python
def filter_alphas_for_optimization(
    alphas: Sequence[Dict],              # alpha结果列表
    alpha_ids: Optional[List[str]] = None,  # 方式1: 精确指定
    min_sharpe: Optional[float] = None,     # 方式2: 条件筛选
    max_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    max_fitness: Optional[float] = None,
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None,
    limit: Optional[int] = None
) -> List[Dict]
```

**示例**:

**场景A: 精确指定alpha_id**
```python
# 用户: "优化这三个alpha: alpha_001, alpha_002, alpha_003"

filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002", "alpha_003"]
)

# AI回复
print(f"筛选出{len(filtered)}个alpha进行优化")
```

**场景B: 按条件筛选**
```python
# 用户: "找出sharpe>1.58, fitness>1.0的alpha"

filtered = filter_alphas_for_optimization(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    limit=50
)

# AI回复
print(f"找到{len(filtered)}个高质量alpha")
```

**场景C: 筛选边缘alpha**
```python
# 用户: "找出sharpe在1.2-1.8之间的边缘alpha"

filtered = filter_alphas_for_optimization(
    alphas,
    min_sharpe=1.2,
    max_sharpe=1.8,
    limit=20
)

# AI决策
if len(filtered) > 0:
    print(f"发现{len(filtered)}个边缘alpha,可以尝试优化")
```

### 2. filter_high_quality_alphas - 高质量alpha

**用途**: 筛选高质量alpha(标准质量门)

**参数**:
```python
def filter_high_quality_alphas(
    alphas: Sequence[Dict],
    min_sharpe: float = 1.58,      # 默认1.58
    min_fitness: float = 1.0,      # 默认1.0
    min_turnover: float = 0.03,    # 默认0.03
    limit: Optional[int] = None
) -> List[Dict]
```

**示例**:
```python
# 筛选高质量alpha
high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    limit=50
)

print(f"找到{len(high_quality)}个高质量alpha")
for a in high_quality:
    print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f}")
```

### 3. filter_marginal_alphas - 边缘alpha

**用途**: 筛选有优化潜力的边缘alpha

**定义**:
- Sharpe在1.2-1.8之间(接近提交线)
- Fitness在0.7-1.5之间(有提升空间)
- Turnover适中(不过高不过低)

**示例**:
```python
# 筛选边缘alpha
marginal = filter_marginal_alphas(
    alphas,
    sharpe_range=(1.2, 1.8),
    fitness_range=(0.7, 1.5),
    limit=20
)

# AI决策
if len(marginal) > 0:
    print(f"发现{len(marginal)}个边缘alpha")
    print("建议:")
    print("  - 调整decay参数")
    print("  - 尝试不同neutralization")
    print("  - 组合group操作")
```

### 4. filter_ready_for_submission - 可提交alpha

**用途**: 筛选满足提交质量门的alpha

**质量门**:
- sharpe ≥ 1.58
- fitness ≥ 1.0
- 0.01 ≤ turnover ≤ 0.7
- long + short ≥ 100

**示例**:
```python
# 筛选可提交的alpha
ready = filter_ready_for_submission(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.01,
    max_turnover=0.7,
    min_long_short_sum=100,
    limit=50
)

print(f"找到{len(ready)}个可提交alpha")
```

### 5. AlphaFilter - 配置类

**用途**: 更灵活的筛选配置

**参数**:
```python
@dataclass
class AlphaFilter:
    # 精确模式
    alpha_ids: Optional[List[str]] = None

    # 条件模式
    min_sharpe: Optional[float] = None
    max_sharpe: Optional[float] = None
    min_fitness: Optional[float] = None
    max_fitness: Optional[float] = None
    min_turnover: Optional[float] = None
    max_turnover: Optional[float] = None

    # 其他条件
    region: Optional[str] = None
    dataset_id: Optional[str] = None
    status: Optional[str] = None

    # 时间范围
    created_after: Optional[str] = None
    created_before: Optional[str] = None

    # 排序与限制
    order_by: str = "sharpe"
    descending: bool = True
    limit: Optional[int] = None
```

**示例**:
```python
# 复杂筛选: EUR市场, sharpe在1.3-1.7之间, 按fitness排序
from alpha_operator_framework.optimize import AlphaFilter, filter_alphas

config = AlphaFilter(
    region="EUR",
    min_sharpe=1.3,
    max_sharpe=1.7,
    order_by="fitness",
    descending=True,
    limit=10
)

filtered = filter_alphas(alphas, config)
```

## 使用场景

### 场景1: 用户指定具体alpha

```python
# 用户: "优化alpha_001, alpha_002这两个alpha"

filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002"]
)

# AI回复
print(f"筛选出{len(filtered)}个alpha")
print("优化建议:")
print("  - 尝试不同decay参数")
print("  - 调整neutralization")
```

### 场景2: 按质量门筛选

```python
# 用户: "找出sharpe>1.58, fitness>1.0, turnover>0.03的alpha"

high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.03
)

# AI回复
print(f"找到{len(high_quality)}个高质量alpha")
for a in high_quality:
    print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f} fitness={a['fitness']:.2f}")
```

### 场景3: 寻找优化机会

```python
# 用户: "哪些alpha有优化潜力?"

marginal = filter_marginal_alphas(alphas)

# AI分析并建议
if len(marginal) > 0:
    print(f"发现{len(marginal)}个边缘alpha,有优化潜力")
    for a in marginal:
        sharpe = a['sharpe']
        gap = 1.58 - sharpe
        print(f"  {a['alpha_id']}: sharpe={sharpe:.2f}, 需提升{gap:.2f}")
        if gap < 0.2:
            print(f"    建议: 调整decay可能达标")
        else:
            print(f"    建议: 尝试组合group操作")
```

### 场景4: 批量处理

```python
# 用户: "EUR和USA市场各找出10个高质量alpha"

results = {}
for region in ["EUR", "USA"]:
    # 先按region筛选
    region_alphas = [a for a in alphas if a.get('region') == region]

    # 再按质量筛选
    results[region] = filter_high_quality_alphas(
        region_alphas,
        min_sharpe=1.58,
        limit=10
    )

# AI回复
for region, filtered in results.items():
    print(f"{region}: {len(filtered)}个高质量alpha")
```

### 场景5: AI决策循环

```python
# AI自动分析alpha池

# 第一步: 筛选高质量alpha
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)

if len(high_quality) >= 5:
    print(f"AI决策: 高质量alpha充足({len(high_quality)}个),建议提交")
    ready = filter_ready_for_submission(alphas)
    print(f"  可提交: {len(ready)}个")

else:
    print(f"AI决策: 高质量alpha不足({len(high_quality)}个),寻找优化机会")

    # 第二步: 筛选边缘alpha
    marginal = filter_marginal_alphas(alphas)

    if len(marginal) > 0:
        print(f"  发现{len(marginal)}个边缘alpha可优化")
        print("  优化策略:")
        print("    - 调整decay参数")
        print("    - 尝试不同neutralization")
        print("    - 组合group操作")
```

## 统计报告

```python
from alpha_operator_framework.optimize import summarize_filtered

# 筛选
config = AlphaFilter(min_sharpe=1.58, limit=10)
filtered = filter_alphas(alphas, config)

# 生成统计报告
report = summarize_filtered(alphas, filtered, config)

print(f"原始数量: {report['total']}")
print(f"筛选数量: {report['passed']}")
print(f"通过率: {report['pass_rate']*100:.1f}%")
print(f"\nSharpe分布:")
print(f"  原始均值: {report['distribution']['sharpe']['original_mean']:.2f}")
print(f"  筛选均值: {report['distribution']['sharpe']['filtered_mean']:.2f}")
```

## 最佳实践

### 1. 分层筛选

```python
# 先粗筛,再细筛
# 粗筛: sharpe > 1.2
coarse = filter_alphas_for_optimization(alphas, min_sharpe=1.2)

# 细筛: sharpe > 1.58, fitness > 1.0
fine = filter_high_quality_alphas(coarse, min_sharpe=1.58)
```

### 2. 条件组合

```python
# 组合多个条件
from alpha_operator_framework.optimize import AlphaFilter, filter_alphas

config = AlphaFilter(
    region="EUR",              # 区域
    min_sharpe=1.3,            # Sharpe下限
    max_sharpe=1.8,            # Sharpe上限
    min_fitness=0.8,           # Fitness下限
    order_by="fitness",        # 按Fitness排序
    limit=20                   # 限制20个
)

filtered = filter_alphas(alphas, config)
```

### 3. AI友好的返回

所有筛选函数返回Python列表,便于AI直接处理:

```python
# AI直接访问结构化结果
filtered = filter_high_quality_alphas(alphas)

for a in filtered:
    alpha_id = a['alpha_id']
    sharpe = a['sharpe']
    fitness = a['fitness']

    # AI做决策
    if sharpe > 1.8:
        print(f"{alpha_id}: 优秀(sharpe={sharpe:.2f})")
    else:
        print(f"{alpha_id}: 良好(sharpe={sharpe:.2f})")
```

## 示例代码

完整示例见: `examples/alpha_filtering_examples.py`

运行:
```bash
python3 examples/alpha_filtering_examples.py
```

## 总结

新增功能:
- ✅ 精确筛选(按alpha_id)
- ✅ 条件筛选(按指标范围)
- ✅ 便捷函数(高质量/边缘/可提交)
- ✅ 配置类(AlphaFilter)
- ✅ 统计报告
- ✅ AI决策支持

框架现已完全支持灵活的alpha筛选与优化!