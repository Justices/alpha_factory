#!/usr/bin/env python
"""
Alpha筛选与优化示例 — 展示如何按条件筛选需要优化的alpha

本示例展示:
  1. 按alpha_id精确筛选
  2. 按回测指标筛选(sharpe/fitness/turnover)
  3. 筛选边缘alpha(有优化潜力)
  4. 筛选可提交的alpha
  5. AI如何根据筛选结果决策
"""

import sys
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    filter_alphas_for_optimization,
    filter_high_quality_alphas,
    filter_marginal_alphas,
    filter_ready_for_submission,
)

from alpha_operator_framework.optimize import (
    AlphaFilter,
    OptimizeConfig,
    summarize_filtered,
)


# ---------------------------------------------------------------------------
# 模拟数据
# ---------------------------------------------------------------------------

def create_mock_alphas():
    """创建模拟的alpha结果列表."""
    return [
        {
            "alpha_id": "alpha_001",
            "expression": "ts_rank(close, 22)",
            "sharpe": 1.85,
            "fitness": 1.45,
            "turnover": 0.05,
            "margin": 0.0035,
            "pnl": 8_500_000,
            "longCount": 75,
            "shortCount": 85,
            "region": "EUR",
        },
        {
            "alpha_id": "alpha_002",
            "expression": "group_neutralize(volume, sector)",
            "sharpe": 1.62,
            "fitness": 1.15,
            "turnover": 0.12,
            "margin": 0.0028,
            "pnl": 5_200_000,
            "longCount": 60,
            "shortCount": 70,
            "region": "EUR",
        },
        {
            "alpha_id": "alpha_003",
            "expression": "ts_delta(returns, 5)",
            "sharpe": 1.45,
            "fitness": 0.92,
            "turnover": 0.08,
            "margin": 0.0021,
            "pnl": 3_800_000,
            "longCount": 55,
            "shortCount": 65,
            "region": "EUR",
        },
        {
            "alpha_id": "alpha_004",
            "expression": "rank(close*volume)",
            "sharpe": 1.20,
            "fitness": 0.78,
            "turnover": 0.04,
            "margin": 0.0018,
            "pnl": 2_500_000,
            "longCount": 50,
            "shortCount": 60,
            "region": "USA",
        },
        {
            "alpha_id": "alpha_005",
            "expression": "ts_regression(close, volume, 22, rettype=2)",
            "sharpe": 0.95,
            "fitness": 0.65,
            "turnover": 0.15,
            "margin": 0.0012,
            "pnl": 1_200_000,
            "longCount": 40,
            "shortCount": 45,
            "region": "USA",
        },
    ]


# ---------------------------------------------------------------------------
# 示例1: 按alpha_id精确筛选
# ---------------------------------------------------------------------------

def example_filter_by_ids():
    """示例: 指定alpha_id列表筛选."""
    print("\n" + "="*70)
    print("示例1: 按alpha_id精确筛选")
    print("="*70)

    alphas = create_mock_alphas()

    # 用户或AI指定要优化的alpha_id列表
    target_ids = ["alpha_001", "alpha_002", "alpha_003"]

    # 筛选
    filtered = filter_alphas_for_optimization(alphas, alpha_ids=target_ids)

    print(f"\n原始: {len(alphas)}个alpha")
    print(f"筛选: {len(filtered)}个alpha")
    print(f"\n筛选结果:")
    for a in filtered:
        print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f} fitness={a['fitness']:.2f}")

    return filtered


# ---------------------------------------------------------------------------
# 示例2: 按回测指标筛选
# ---------------------------------------------------------------------------

def example_filter_by_metrics():
    """示例: 按sharpe/fitness/turnover筛选."""
    print("\n" + "="*70)
    print("示例2: 按回测指标筛选")
    print("="*70)

    alphas = create_mock_alphas()

    # 筛选高质量alpha: sharpe>1.58, fitness>1.0, turnover>0.03
    print("\n筛选高质量alpha (sharpe≥1.58, fitness≥1.0, turnover≥0.03):")
    high_quality = filter_high_quality_alphas(
        alphas,
        min_sharpe=1.58,
        min_fitness=1.0,
        min_turnover=0.03
    )

    print(f"  找到{len(high_quality)}个:")
    for a in high_quality:
        print(f"    {a['alpha_id']}: sharpe={a['sharpe']:.2f} fitness={a['fitness']:.2f}")

    # 筛选需要优化的alpha
    print("\n筛选待优化alpha (sharpe在1.2-1.8之间):")
    to_optimize = filter_alphas_for_optimization(
        alphas,
        min_sharpe=1.2,
        max_sharpe=1.8,
        limit=10
    )

    print(f"  找到{len(to_optimize)}个:")
    for a in to_optimize:
        print(f"    {a['alpha_id']}: sharpe={a['sharpe']:.2f}")

    return high_quality, to_optimize


# ---------------------------------------------------------------------------
# 示例3: 筛选边缘alpha
# ---------------------------------------------------------------------------

def example_filter_marginal():
    """示例: 筛选边缘alpha(有优化潜力)."""
    print("\n" + "="*70)
    print("示例3: 筛选边缘alpha(有优化潜力)")
    print("="*70)

    alphas = create_mock_alphas()

    # 边缘alpha: sharpe在1.2-1.8之间,有提升空间
    print("\n边缘alpha定义:")
    print("  - Sharpe: 1.2-1.8 (接近提交线)")
    print("  - Fitness: 0.7-1.5 (有提升空间)")
    print("  - Turnover: 0.01-0.1 (适中)")

    marginal = filter_marginal_alphas(
        alphas,
        sharpe_range=(1.2, 1.8),
        fitness_range=(0.7, 1.5),
        turnover_range=(0.01, 0.1),
        limit=20
    )

    print(f"\n找到{len(marginal)}个边缘alpha:")
    for a in marginal:
        print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f} fitness={a['fitness']:.2f}")

    # AI决策
    print("\nAI决策:")
    if len(marginal) > 0:
        print(f"  ✓ 发现{len(marginal)}个边缘alpha,可以尝试优化:")
        print(f"    - 调整decay参数")
        print(f"    - 尝试不同neutralization")
        print(f"    - 组合group操作")

    return marginal


# ---------------------------------------------------------------------------
# 示例4: 筛选可提交的alpha
# ---------------------------------------------------------------------------

def example_filter_ready_for_submission():
    """示例: 筛选可提交的alpha."""
    print("\n" + "="*70)
    print("示例4: 筛选可提交的alpha")
    print("="*70)

    alphas = create_mock_alphas()

    # 提交质量门
    print("\n提交质量门:")
    print("  - sharpe ≥ 1.58")
    print("  - fitness ≥ 1.0")
    print("  - 0.01 ≤ turnover ≤ 0.7")
    print("  - long + short ≥ 100")

    ready = filter_ready_for_submission(
        alphas,
        min_sharpe=1.58,
        min_fitness=1.0,
        min_turnover=0.01,
        max_turnover=0.7,
        min_long_short_sum=100,
        limit=50
    )

    print(f"\n找到{len(ready)}个可提交alpha:")
    for a in ready:
        total_positions = a['longCount'] + a['shortCount']
        print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f} fitness={a['fitness']:.2f} positions={total_positions}")

    return ready


# ---------------------------------------------------------------------------
# 示例5: 组合筛选
# ---------------------------------------------------------------------------

def example_combined_filtering():
    """示例: 组合多种筛选条件."""
    print("\n" + "="*70)
    print("示例5: 组合筛选")
    print("="*70)

    alphas = create_mock_alphas()

    # 场景: 用户想优化EUR市场的某些alpha
    print("\n场景: 优化EUR市场sharpe在1.3-1.7之间的alpha")

    # 方法1: 使用AlphaFilter配置类
    from alpha_operator_framework.optimize import AlphaFilter, filter_alphas

    config = AlphaFilter(
        region="EUR",
        min_sharpe=1.3,
        max_sharpe=1.7,
        order_by="sharpe",
        descending=True,
        limit=10
    )

    filtered = filter_alphas(alphas, config)

    print(f"\n找到{len(filtered)}个:")
    for a in filtered:
        print(f"  {a['alpha_id']}: sharpe={a['sharpe']:.2f} region={a['region']}")

    # 生成统计报告
    report = summarize_filtered(alphas, filtered, config)

    print("\n统计报告:")
    print(f"  原始数量: {report['total']}")
    print(f"  筛选数量: {report['passed']}")
    print(f"  通过率: {report['pass_rate']*100:.1f}%")

    return filtered


# ---------------------------------------------------------------------------
# 示例6: AI决策循环
# ---------------------------------------------------------------------------

def example_ai_decision_loop():
    """示例: AI根据筛选结果决策优化策略."""
    print("\n" + "="*70)
    print("示例6: AI决策循环")
    print("="*70)

    alphas = create_mock_alphas()

    # 第一步: 找出高质量alpha
    print("\n第一步: 筛选高质量alpha")
    high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)

    print(f"  找到{len(high_quality)}个高质量alpha")

    # AI决策1
    if len(high_quality) >= 2:
        print("\nAI决策: 高质量alpha充足,准备提交")
        print(f"  建议: 对这{len(high_quality)}个alpha进行提交检查")

    # 第二步: 找出边缘alpha
    print("\n第二步: 筛选边缘alpha")
    marginal = filter_marginal_alphas(alphas, sharpe_range=(1.2, 1.8))

    print(f"  找到{len(marginal)}个边缘alpha")

    # AI决策2
    if len(marginal) > 0:
        print("\nAI决策: 发现可优化的边缘alpha")
        print(f"  建议: 对这{len(marginal)}个alpha尝试优化:")
        print(f"    - alpha_003: sharpe=1.45, 调整decay可能提升到1.6+")
        print(f"    - alpha_004: sharpe=1.20, 尝试组合group操作")

    # 第三步: 筛选低质量alpha(放弃)
    low_quality = [a for a in alphas if a['sharpe'] < 1.2]

    if low_quality:
        print(f"\n第三步: 低质量alpha {len(low_quality)}个")
        print("  建议: 暂不处理,等待更好的机会")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main():
    """运行所有示例."""
    print("\n" + "="*70)
    print("Alpha筛选与优化示例")
    print("="*70)

    example_filter_by_ids()
    example_filter_by_metrics()
    example_filter_marginal()
    example_filter_ready_for_submission()
    example_combined_filtering()
    example_ai_decision_loop()

    print("\n" + "="*70)
    print("所有示例完成!")
    print("="*70)

    print("\n关键点:")
    print("  1. 支持按alpha_id精确筛选")
    print("  2. 支持按回测指标筛选(sharpe/fitness/turnover)")
    print("  3. 可筛选边缘alpha(有优化潜力)")
    print("  4. 可筛选可提交的alpha")
    print("  5. 支持组合筛选(region/dataset等)")
    print("  6. AI可根据筛选结果决策优化策略")


if __name__ == "__main__":
    main()