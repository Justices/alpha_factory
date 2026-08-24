# Alpha 因子多维筛选与质量门禁指南 (Alpha Filtering Guide)

> **定位**: 介绍 `alpha_operator_framework/domain/optimize.py` 模块的 Alpha 因子多维筛选、优化队列分派与质量门禁。

---

## 一、 功能概述

框架提供了灵活高效的 Alpha 筛选工具：
1. **精确筛选**: 按平台 `alpha_id` 列表精确提取；
2. **条件筛选**: 按实测绩效指标（Sharpe, Fitness, Turnover, Margin）范围过滤；
3. **预定义场景门禁**: 高质量池（Sharpe $\ge 1.58$）、边缘池（$1.2 \le \text{Sharpe} < 1.58$）、可提交候选池；
4. **统计与分布报告**: 筛选结果综合度量。

---

## 二、 核心 Python API

```python
from alpha_operator_framework.domain.optimize import (
    filter_alphas_for_optimization,
    filter_high_quality_alphas,
    filter_marginal_alphas,
    generate_optimization_report,
)

# 假设已有回测结果列表 alphas
# 1. 筛选高质量 Alpha (Sharpe >= 1.25, Fitness >= 1.0, Turnover in [0.01, 0.70])
high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.25, min_fitness=1.0)
print(f"高质量 Alpha 数量: {len(high_quality)}")

# 2. 筛选具有优化潜力的边缘 Alpha (用于二代变异重构)
marginal = filter_marginal_alphas(alphas, min_sharpe=0.8, max_sharpe=1.25)
print(f"边缘 Alpha 数量: {len(marginal)}")

# 3. 生成优化报告
report = generate_optimization_report(alphas)
print(report)
```

---

## 三、 CLI 命令行调用

```bash
# 按指标筛选潜力候选
python alpha_machine.py filter \
    --results runs/results.json \
    --sharpe 1.25 --fitness 1.0 --margin 5.0 \
    --min-turnover 0.01 --max-turnover 0.70 \
    --output runs/filtered_alphas.json
```