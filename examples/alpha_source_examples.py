#!/usr/bin/env python
"""
Alpha获取示例 — 展示如何从不同来源获取alpha列表

本示例展示:
  1. 从工作流结果获取 (survey/deepen的结果)
  2. 从文件读取 (JSON)
  3. 从平台查询 (alpha_machine)
  4. 一站式获取并筛选
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    filter_alphas_for_optimization,
    filter_high_quality_alphas,
)

from alpha_operator_framework.alpha_source import (
    get_alphas_from_workflow_result,
    load_alphas_from_file,
    fetch_user_alphas,
    fetch_alpha_by_ids,
    get_and_filter_alphas,
)


# ---------------------------------------------------------------------------
# 示例1: 从工作流结果获取
# ---------------------------------------------------------------------------

async def example_from_workflow():
    """示例: 从survey/deepen的结果中获取alpha."""
    print("\n" + "="*70)
    print("示例1: 从工作流结果获取")
    print("="*70)

    # 假设已经运行过工作流
    from alpha_operator_framework import run_full_workflow, FieldSpec

    # 运行工作流(dry-run)
    field_specs = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92),
    ]

    result = await run_full_workflow(
        region="EUR",
        universe="TOP2500",
        field_ids=["close", "volume"],
        field_specs=field_specs,
        execute=False  # dry-run
    )

    # 从结果中提取alpha
    alphas = get_alphas_from_workflow_result(result, "survey")

    print(f"\n从工作流结果获取: {len(alphas)}个alpha")

    # 再进行筛选
    if alphas:
        filtered = filter_high_quality_alphas(alphas, min_sharpe=1.58)
        print(f"筛选后: {len(filtered)}个高质量alpha")


# ---------------------------------------------------------------------------
# 示例2: 从文件读取
# ---------------------------------------------------------------------------

def example_from_file():
    """示例: 从JSON文件读取alpha列表."""
    print("\n" + "="*70)
    print("示例2: 从文件读取")
    print("="*70)

    # 模拟文件路径(实际使用时替换为真实路径)
    file_path = "runs/survey_results_EUR_pv1.json"

    print(f"\n从文件读取: {file_path}")

    # 检查文件是否存在
    if not Path(file_path).exists():
        print("  文件不存在(这是模拟示例)")
        print("\n  实际使用:")
        print("    # 1. 先运行工作流生成文件:")
        print("    result = await run_full_workflow(..., execute=True)")
        print("    ")
        print("    # 2. 然后从文件读取:")
        print("    alphas = load_alphas_from_file('runs/survey_results_EUR_pv1.json')")
        print("    ")
        print("    # 3. 再筛选:")
        print("    filtered = filter_high_quality_alphas(alphas, min_sharpe=1.58)")
        return

    # 读取alpha
    alphas = load_alphas_from_file(file_path)
    print(f"  读取到{len(alphas)}个alpha")

    # 筛选
    filtered = filter_high_quality_alphas(alphas, min_sharpe=1.58)
    print(f"  筛选后: {len(filtered)}个高质量alpha")


# ---------------------------------------------------------------------------
# 示例3: 从平台查询
# ---------------------------------------------------------------------------

async def example_from_platform():
    """示例: 从BRAIN平台查询用户的alpha."""
    print("\n" + "="*70)
    print("示例3: 从平台查询")
    print("="*70)

    print("\n查询用户的alpha列表...")

    # 方式A: 按条件查询
    try:
        alphas = await fetch_user_alphas(
            region="EUR",         # EUR市场
            status="IS",          # 未提交的alpha
            min_sharpe=1.2,       # Sharpe > 1.2
            limit=50              # 最多50个
        )

        print(f"  查询到{len(alphas)}个alpha")

        # 再进行更严格的筛选
        filtered = filter_high_quality_alphas(alphas, min_sharpe=1.58)
        print(f"  筛选后: {len(filtered)}个高质量alpha")

    except ImportError:
        print("  ⚠ 未安装alpha_machine")
        print("  安装: pip install alpha_machine")
        print("  配置: 设置BRAIN_EMAIL和BRAIN_PASSWORD环境变量")

    # 方式B: 按alpha_id查询
    print("\n按alpha_id精确查询...")
    try:
        alphas = await fetch_alpha_by_ids(["alpha_001", "alpha_002", "alpha_003"])
        print(f"  查询到{len(alphas)}个alpha")

        for a in alphas:
            print(f"    {a['alpha_id']}: sharpe={a.get('sharpe', 0):.2f}")

    except ImportError:
        pass


# ---------------------------------------------------------------------------
# 示例4: 一站式获取并筛选
# ---------------------------------------------------------------------------

async def example_one_stop():
    """示例: 一步完成获取和筛选."""
    print("\n" + "="*70)
    print("示例4: 一站式获取并筛选")
    print("="*70)

    # 场景A: 从平台查询并筛选
    print("\n场景A: 从平台查询EUR市场的alpha,并筛选sharpe>1.58")
    try:
        filtered = await get_and_filter_alphas(
            source="platform",
            region="EUR",
            status="IS",
            min_sharpe=1.58,       # 平台已筛选
            limit=50
        )
        print(f"  结果: {len(filtered)}个高质量alpha")

    except ImportError:
        print("  (需要alpha_machine)")

    # 场景B: 从文件读取并筛选边缘alpha
    print("\n场景B: 从文件读取,筛选sharpe在1.2-1.8之间的边缘alpha")
    filtered = await get_and_filter_alphas(
        source="file",
        file_path="runs/survey_results_EUR_pv1.json",
        min_sharpe=1.2,
        max_sharpe=1.8,
        limit=20
    )
    print(f"  结果: {len(filtered)}个边缘alpha")

    # 场景C: 指定alpha_id查询
    print("\n场景C: 指定alpha_id查询")
    try:
        filtered = await get_and_filter_alphas(
            source="platform",
            alpha_ids=["alpha_001", "alpha_002"]
        )
        print(f"  结果: {len(filtered)}个alpha")

    except ImportError:
        print("  (需要alpha_machine)")


# ---------------------------------------------------------------------------
# 示例5: AI典型工作流
# ---------------------------------------------------------------------------

async def example_ai_workflow():
    """示例: AI的典型工作流程."""
    print("\n" + "="*70)
    print("示例5: AI典型工作流")
    print("="*70)

    print("\nAI工作流程:")
    print("  1. 运行survey调研")
    print("  2. 从结果文件读取alpha")
    print("  3. 筛选需要优化的alpha")
    print("  4. 提供优化建议")

    # 步骤1: 运行工作流
    print("\n步骤1: 运行survey调研")
    from alpha_operator_framework import run_full_workflow, FieldSpec

    field_specs = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX"),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX"),
    ]

    result = await run_full_workflow(
        region="EUR",
        universe="TOP2500",  # 添加universe参数
        field_ids=["close", "volume"],
        field_specs=field_specs,
        execute=False  # AI先dry-run
    )

    print(f"  任务: {result['survey'].tasks_generated}个")

    # 步骤2: (假设已执行)从文件读取
    print("\n步骤2: 从结果文件读取alpha")
    print("  (实际使用时需要execute=True生成文件)")

    # 步骤3: 筛选
    print("\n步骤3: 筛选需要优化的alpha")
    print("  筛选条件: sharpe在1.2-1.8之间(边缘alpha)")

    # 步骤4: AI建议
    print("\n步骤4: AI提供优化建议")
    print("  对于边缘alpha,建议:")
    print("    - 调整decay参数(尝试3.0/6.0/9.0)")
    print("    - 尝试不同neutralization(MARKET/SECTOR)")
    print("    - 组合group操作(group_rank/group_neutralize)")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def main():
    """运行所有示例."""
    print("\n" + "="*70)
    print("Alpha获取示例 — 从不同来源获取alpha列表")
    print("="*70)

    await example_from_workflow()
    example_from_file()
    await example_from_platform()
    await example_one_stop()
    await example_ai_workflow()

    print("\n" + "="*70)
    print("所有示例完成!")
    print("="*70)

    print("\n关键点:")
    print("  1. 从工作流结果: get_alphas_from_workflow_result()")
    print("  2. 从文件读取: load_alphas_from_file()")
    print("  3. 从平台查询: fetch_user_alphas() / fetch_alpha_by_ids()")
    print("  4. 一站式: get_and_filter_alphas()")
    print("\n典型流程:")
    print("  survey → 保存结果文件 → 读取文件 → 筛选 → 优化")


if __name__ == "__main__":
    asyncio.run(main())