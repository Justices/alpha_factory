# Alpha筛选功能改进总结

## 改进背景

**用户需求**: 在筛选需要优化的alpha时，希望能够：
1. 指定alpha_id列表（精确控制）
2. 或按回测结果条件筛选（sharpe>1.58, fitness>1.0, turnover>3等）

**解决方案**: 新增 `optimize.py` 模块，提供灵活的alpha筛选API。

## 核心功能

### 1. 两种筛选模式

**模式A: 精确指定**
```python
# 用户: "优化这三个alpha: alpha_001, alpha_002, alpha_003"
filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002", "alpha_003"]
)
```

**模式B: 条件筛选**
```python
# 用户: "找出sharpe>1.58, fitness>1.0的alpha"
filtered = filter_alphas_for_optimization(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_turnover=0.03
)
```

### 2. 便捷筛选函数

**高质量alpha**:
```python
# 标准质量门: sharpe≥1.58, fitness≥1.0, turnover≥0.03
high_quality = filter_high_quality_alphas(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    limit=50
)
```

**边缘alpha**:
```python
# 有优化潜力: sharpe在1.2-1.8之间
marginal = filter_marginal_alphas(
    alphas,
    sharpe_range=(1.2, 1.8),
    limit=20
)
```

**可提交alpha**:
```python
# 满足提交质量门
ready = filter_ready_for_submission(
    alphas,
    min_sharpe=1.58,
    min_fitness=1.0,
    min_long_short_sum=100
)
```

### 3. 灵活配置类

```python
from alpha_operator_framework.optimize import AlphaFilter, filter_alphas

# 组合多条件
config = AlphaFilter(
    region="EUR",              # 区域筛选
    min_sharpe=1.3,            # Sharpe范围
    max_sharpe=1.8,
    min_fitness=0.8,           # Fitness下限
    order_by="fitness",        # 按Fitness排序
    descending=True,           # 降序
    limit=10                   # 限制数量
)

filtered = filter_alphas(alphas, config)
```

## API设计

### filter_alphas_for_optimization
```python
def filter_alphas_for_optimization(
    alphas: Sequence[Dict],              # alpha结果列表
    alpha_ids: Optional[List[str]] = None,  # 精确模式
    min_sharpe: Optional[float] = None,     # 条件模式
    max_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    max_fitness: Optional[float] = None,
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None,
    limit: Optional[int] = None
) -> List[Dict]
```

### AlphaFilter配置类
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
    min_margin: Optional[float] = None
    max_margin: Optional[float] = None
    min_pnl: Optional[float] = None
    max_pnl: Optional[float] = None

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

## 使用场景

### 场景1: 用户指定alpha_id

```python
# 用户: "优化alpha_001, alpha_002"
filtered = filter_alphas_for_optimization(
    alphas,
    alpha_ids=["alpha_001", "alpha_002"]
)

# AI回复
print(f"筛选出{len(filtered)}个alpha进行优化")
for a in filtered:
    print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f}")
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
```

### 场景3: 寻找优化机会

```python
# 用户: "哪些alpha有优化潜力?"
marginal = filter_marginal_alphas(alphas)

# AI分析
for a in marginal:
    sharpe = a['sharpe']
    gap = 1.58 - sharpe
    print(f"{a['alpha_id']}: sharpe={sharpe:.2f}, 需提升{gap:.2f}")
    if gap < 0.2:
        print(f"  建议: 调整decay参数")
    else:
        print(f"  建议: 尝试组合group操作")
```

### 场景4: AI决策循环

```python
# AI自动分析alpha池

# 第一步: 筛选高质量alpha
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)

if len(high_quality) >= 5:
    print(f"AI决策: 高质量alpha充足({len(high_quality)}个)")
    print("建议: 直接提交")
else:
    print(f"AI决策: 高质量alpha不足({len(high_quality)}个)")

    # 第二步: 寻找优化机会
    marginal = filter_marginal_alphas(alphas)

    if len(marginal) > 0:
        print(f"发现{len(marginal)}个边缘alpha可优化")
```

## 实现细节

### 1. matches方法

```python
class AlphaFilter:
    def matches(self, alpha: Dict[str, Any]) -> bool:
        """检查alpha是否满足所有筛选条件."""
        # 精确模式: 检查alpha_id
        if self.alpha_ids:
            alpha_id = alpha.get("alpha_id") or alpha.get("id")
            if alpha_id not in self.alpha_ids:
                return False

        # 条件模式: 检查指标范围
        if not self._check_metric(alpha, "sharpe", self.min_sharpe, self.max_sharpe):
            return False

        # ...其他指标检查

        return True
```

### 2. filter_alphas函数

```python
def filter_alphas(
    alphas: Sequence[Dict],
    filter_config: AlphaFilter
) -> List[Dict]:
    # 应用筛选条件
    filtered = [a for a in alphas if filter_config.matches(a)]

    # 排序
    filtered.sort(key=lambda a: a.get(filter_config.order_by, 0),
                  reverse=filter_config.descending)

    # 限制数量
    if filter_config.limit:
        filtered = filtered[:filter_config.limit]

    return filtered
```

### 3. 统计报告

```python
def summarize_filtered(
    original: Sequence[Dict],
    filtered: Sequence[Dict],
    filter_config: AlphaFilter
) -> Dict[str, Any]:
    """生成筛选统计报告."""
    return {
        "total": len(original),
        "passed": len(filtered),
        "pass_rate": len(filtered) / len(original),
        "filter_config": filter_config.__dict__,
        "distribution": {
            metric: {
                "original_mean": ...,
                "filtered_mean": ...,
            }
            for metric in ["sharpe", "fitness", "turnover", "margin"]
        }
    }
```

## 新增文件

```
alpha_operator_framework/
└── optimize.py              # ✨ 新增: Alpha筛选模块

examples/
└── alpha_filtering_examples.py  # ✨ 新增: 6个完整示例

docs/
└── ALPHA_FILTERING.md       # ✨ 新增: 筛选功能文档
```

## 验证结果

```bash
$ python3 examples/alpha_filtering_examples.py

示例1: 按alpha_id精确筛选
  ✓ 筛选出3个alpha

示例2: 按回测指标筛选
  ✓ 找到2个高质量alpha
  ✓ 找到3个待优化alpha

示例3: 筛选边缘alpha
  ✓ 找到2个边缘alpha(有优化潜力)

示例4: 筛选可提交的alpha
  ✓ 找到2个可提交alpha

示例5: 组合筛选
  ✓ EUR市场: 2个alpha, 通过率40%

示例6: AI决策循环
  ✓ 高质量alpha: 2个
  ✓ 边缘alpha: 2个(可优化)

✓ 所有示例完成!
```

## 对比：改进前后

| 特性 | 改进前 | 改进后 |
|------|--------|--------|
| **精确筛选** | 无 | ✅ 支持alpha_id列表 |
| **条件筛选** | 无 | ✅ 支持指标范围 |
| **便捷函数** | 无 | ✅ 4个预定义函数 |
| **组合条件** | 无 | ✅ AlphaFilter配置类 |
| **统计报告** | 无 | ✅ summarize_filtered |
| **AI决策** | 无 | ✅ 结构化返回 |

## 最佳实践

1. **分层筛选**: 先粗筛(宽松条件),再细筛(严格条件)
2. **组合条件**: 使用AlphaFilter配置类组合多条件
3. **统计报告**: 用summarize_filtered分析筛选效果
4. **AI决策**: 基于筛选结果自动决策优化策略

## 后续优化

1. **更多指标**: 支持更多回测指标筛选
2. **智能推荐**: AI自动推荐筛选条件
3. **批量优化**: 批量生成优化变体
4. **结果追踪**: 追踪优化前后效果对比

## 总结

本次改进核心:
- ✅ 新增optimize.py模块
- ✅ 支持精确筛选(alpha_id列表)
- ✅ 支持条件筛选(指标范围)
- ✅ 4个便捷函数(高质量/边缘/可提交/通用)
- ✅ AlphaFilter配置类
- ✅ 统计报告功能
- ✅ 完整示例与文档

框架现已完全支持灵活的alpha筛选与优化!