#!/usr/bin/env python
"""
分页获取示例 — 展示如何分页获取大量alpha

本示例展示:
  1. 分页获取所有alpha
  2. 控制每页数量和最大页数
  3. 批量查询大量alpha_id
  4. 失败重试机制
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    fetch_user_alphas,
    fetch_alpha_by_ids,
    filter_high_quality_alphas,
)


# ---------------------------------------------------------------------------
# 示例1: 分页获取所有alpha
# ---------------------------------------------------------------------------

async def example_fetch_all_alphas():
    """示例: 获取EUR市场所有未提交的alpha."""
    print("\n" + "="*70)
    print("示例1: 分页获取所有alpha")
    print("="*70)

    print("\n场景: 获取EUR市场所有未提交的alpha")
    print("参数:")
    print("  - region: EUR")
    print("  - status: IS (未提交)")
    print("  - limit: 0 (获取全部)")
    print("  - page_size: 100 (每页100个)")
    print("  - max_pages: 20 (最多20页)")

    try:
        alphas = await fetch_user_alphas(
            region="EUR",
            status="IS",
            limit=0,           # 0表示获取全部
            page_size=100,     # 每页100个
            max_pages=20,      # 最多20页=最多2000个
            enable_pagination=True
        )

        print(f"\n总计获取: {len(alphas)}个alpha")

        # 筛选高质量alpha
        high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
        print(f"高质量alpha: {len(high_quality)}个")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")
        print("  安装: pip install alpha_machine")


# ---------------------------------------------------------------------------
# 示例2: 限制总数获取
# ---------------------------------------------------------------------------

async def example_fetch_with_limit():
    """示例: 限制获取总数."""
    print("\n" + "="*70)
    print("示例2: 限制总数获取")
    print("="*70)

    print("\n场景: 获取前500个高质量alpha")
    print("参数:")
    print("  - min_sharpe: 1.2 (平台侧筛选)")
    print("  - limit: 500 (最多500个)")
    print("  - page_size: 100 (每页100个)")

    try:
        alphas = await fetch_user_alphas(
            min_sharpe=1.2,    # 平台已筛选
            limit=500,         # 总数限制
            page_size=100,     # 每页100个
            enable_pagination=True
        )

        print(f"\n总计获取: {len(alphas)}个alpha")

        # 进一步筛选
        high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
        print(f"进一步筛选: {len(high_quality)}个高质量alpha")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")


# ---------------------------------------------------------------------------
# 示例3: 单页获取(不分页)
# ---------------------------------------------------------------------------

async def example_fetch_single_page():
    """示例: 只获取第一页(不分页)."""
    print("\n" + "="*70)
    print("示例3: 单页获取(不分页)")
    print("="*70)

    print("\n场景: 快速获取前50个alpha")
    print("参数:")
    print("  - limit: 50")
    print("  - enable_pagination: False (不分页)")

    try:
        alphas = await fetch_user_alphas(
            region="EUR",
            limit=50,
            page_size=50,
            enable_pagination=False  # 只获取第一页
        )

        print(f"\n获取: {len(alphas)}个alpha")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")


# ---------------------------------------------------------------------------
# 示例4: 批量查询alpha_id
# ---------------------------------------------------------------------------

async def example_batch_fetch_by_ids():
    """示例: 批量查询大量alpha_id."""
    print("\n" + "="*70)
    print("示例4: 批量查询alpha_id")
    print("="*70)

    print("\n场景: 查询100个指定的alpha_id")
    print("参数:")
    print("  - batch_size: 20 (每批20个)")
    print("  - max_retries: 3 (失败重试3次)")

    # 模拟100个alpha_id
    alpha_ids = [f"alpha_{i:03d}" for i in range(1, 101)]

    print(f"\n准备查询{len(alpha_ids)}个alpha")

    try:
        alphas = await fetch_alpha_by_ids(
            alpha_ids,
            batch_size=20,    # 每批20个
            max_retries=3     # 失败重试3次
        )

        print(f"\n成功获取: {len(alphas)}/{len(alpha_ids)}个alpha")

        # 统计失败率
        success_rate = len(alphas) / len(alpha_ids) * 100
        print(f"成功率: {success_rate:.1f}%")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")


# ---------------------------------------------------------------------------
# 示例5: 控制分页速度
# ---------------------------------------------------------------------------

async def example_control_pagination_speed():
    """示例: 控制分页速度."""
    print("\n" + "="*70)
    print("示例5: 控制分页速度")
    print("="*70)

    print("\n场景: 慢速分页(每页50个,最多10页)")
    print("  防止触发平台限流")

    try:
        alphas = await fetch_user_alphas(
            region="EUR",
            limit=0,
            page_size=50,    # 每页较少
            max_pages=10,    # 限制页数
            enable_pagination=True
        )

        print(f"\n获取: {len(alphas)}个alpha")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")


# ---------------------------------------------------------------------------
# 示例6: AI典型场景
# ---------------------------------------------------------------------------

async def example_ai_scenario():
    """示例: AI典型使用场景."""
    print("\n" + "="*70)
    print("示例6: AI典型场景")
    print("="*70)

    print("\n场景: AI分析用户所有alpha并分类")

    try:
        # 步骤1: 获取所有alpha
        print("\n步骤1: 获取所有alpha")
        alphas = await fetch_user_alphas(
            status="IS",
            limit=0,          # 全部
            page_size=100,
            max_pages=50      # 最多5000个
        )

        print(f"  总计: {len(alphas)}个alpha")

        # 步骤2: 分类
        print("\n步骤2: 分类")
        high_quality = filter_high_quality_alphas(alphas, min_sharpe=1.58)
        print(f"  高质量(sharpe≥1.58): {len(high_quality)}个")

        from alpha_operator_framework import filter_marginal_alphas
        marginal = filter_marginal_alphas(alphas, sharpe_range=(1.2, 1.8))
        print(f"  边缘(1.2-1.8): {len(marginal)}个")

        low_quality = [a for a in alphas if a.get('sharpe', 0) < 1.2]
        print(f"  低质量(<1.2): {len(low_quality)}个")

        # 步骤3: AI建议
        print("\n步骤3: AI建议")
        if len(high_quality) > 10:
            print("  ✓ 高质量alpha充足,建议直接提交")
        elif len(marginal) > 5:
            print("  ⚠ 高质量alpha不足,但边缘alpha较多")
            print("  建议: 尝试优化边缘alpha")
        else:
            print("  ✗ alpha池整体质量偏低")
            print("  建议: 扩大调研范围或调整策略")

    except ImportError:
        print("\n⚠ 未安装alpha_machine")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def main():
    """运行所有示例."""
    print("\n" + "="*70)
    print("分页获取示例 — Alpha Operator Framework")
    print("="*70)

    await example_fetch_all_alphas()
    await example_fetch_with_limit()
    await example_fetch_single_page()
    await example_batch_fetch_by_ids()
    await example_control_pagination_speed()
    await example_ai_scenario()

    print("\n" + "="*70)
    print("所有示例完成!")
    print("="*70)

    print("\n关键参数:")
    print("  - limit: 总数限制 (0=获取全部)")
    print("  - page_size: 每页数量 (默认50)")
    print("  - max_pages: 最大页数 (默认20)")
    print("  - enable_pagination: 是否分页 (默认True)")
    print("  - batch_size: 批量查询数量 (默认10)")
    print("  - max_retries: 失败重试次数 (默认3)")

    print("\n最佳实践:")
    print("  1. 获取全部: limit=0, page_size=100, max_pages=50")
    print("  2. 限制总数: limit=500, page_size=100")
    print("  3. 快速预览: limit=50, enable_pagination=False")
    print("  4. 批量查询: batch_size=20, max_retries=3")


if __name__ == "__main__":
    asyncio.run(main())