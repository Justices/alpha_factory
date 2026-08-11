#!/usr/bin/env python
"""
AI调用示例 — 展示如何精确控制参数和字段列表

本示例展示:
  1. 如何指定区域、宇宙、数据集
  2. 如何指定精确的字段列表(而非随机采样)
  3. 如何获取结构化结果
  4. AI如何解析结果并继续工作
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    FieldSpec,
    SurveyConfig,
    DeepenConfig,
    WorkflowResult,
)

from alpha_operator_framework.ai_workflow import (
    run_survey_with_fields,
    run_full_workflow,
)


# ---------------------------------------------------------------------------
# 示例1: 使用精确字段列表
# ---------------------------------------------------------------------------

async def example_precise_fields():
    """示例: 指定精确的字段列表,不随机采样."""
    print("\n" + "="*70)
    print("示例1: 使用精确字段列表")
    print("="*70)

    # AI或用户提供精确的字段列表
    field_specs = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92),
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.99),
        FieldSpec(id="cap", dataset_id="pv1", type="MATRIX", coverage=0.95),
    ]

    # 精确指定要使用的字段
    config = SurveyConfig(
        region="EUR",
        universe="TOP2500",
        delay=1,
        dataset_id="pv1",
        field_ids=["close", "volume", "returns"],  # 只用这3个字段
        include_unary=True,
        include_binary=True,
        include_ternary=False,
    )

    # 运行survey(dry-run)
    result = await run_survey_with_fields(
        field_specs,
        config,
        output_dir=Path("runs/example1"),
        execute=False  # AI可以先dry-run查看任务
    )

    # AI解析结果
    print(f"\n结果:")
    print(f"  成功: {result.success}")
    print(f"  消息: {result.message}")
    print(f"  任务数: {result.tasks_generated}")

    if result.tasks_file:
        print(f"  任务文件: {result.tasks_file}")

    return result


# ---------------------------------------------------------------------------
# 示例2: 完整三段工作流(单次调用)
# ---------------------------------------------------------------------------

async def example_full_workflow():
    """示例: 单次调用完成survey→deepen→submit."""
    print("\n" + "="*70)
    print("示例2: 完整三段工作流")
    print("="*70)

    # 指定参数
    field_specs = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92),
    ]

    # 单次调用
    results = await run_full_workflow(
        region="EUR",
        universe="TOP2500",
        delay=1,
        dataset_id="pv1",
        field_ids=["close", "volume"],  # 指定字段
        field_specs=field_specs,        # 提供字段规格(避免查询平台)
        sample_n=80,
        top_n=3,
        min_sharpe=1.2,
        execute=False  # AI可以先dry-run
    )

    # AI解析各阶段结果
    for stage, result in results.items():
        print(f"\n{stage.upper()}阶段:")
        print(f"  成功: {result.success}")
        print(f"  消息: {result.message}")

        if stage == "survey":
            print(f"  任务数: {result.tasks_generated}")
            if result.top_templates:
                print(f"  Top模板: {len(result.top_templates)}")
                for t in result.top_templates[:3]:
                    print(f"    - [{t['family']}/{t['template_index']}] density={t['density']:.2f}")

        elif stage == "deepen":
            print(f"  候选数: {len(result.candidates)}")
            for c in result.candidates[:3]:
                print(f"    - {c.get('alpha_id')} sharpe={c.get('sharpe'):.2f}")

        elif stage == "submit":
            print(f"  候选alpha: {len(result.candidates)}")

    return results


# ---------------------------------------------------------------------------
# 示例3: AI决策循环
# ---------------------------------------------------------------------------

async def example_ai_decision_loop():
    """示例: AI根据结果决策下一步."""
    print("\n" + "="*70)
    print("示例3: AI决策循环")
    print("="*70)

    # 第一步: 先用少量字段快速调研
    print("\n第一步: 快速调研(2个字段)")
    field_specs_1 = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92),
    ]

    result_1 = await run_survey_with_fields(
        field_specs_1,
        SurveyConfig(region="EUR", universe="TOP2500", field_ids=["close", "volume"]),
        execute=False
    )

    print(f"  结果: {result_1.message}")

    # AI决策: 如果密度太低,尝试其他字段
    if result_1.top_templates and result_1.top_templates[0]["density"] < 0.1:
        print("\nAI决策: 密度较低,尝试其他字段")

        # 第二步: 扩展字段列表
        print("\n第二步: 扩展字段(增加returns)")
        field_specs_2 = field_specs_1 + [
            FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.99)
        ]

        result_2 = await run_survey_with_fields(
            field_specs_2,
            SurveyConfig(region="EUR", universe="TOP2500", field_ids=["close", "volume", "returns"]),
            execute=False
        )

        print(f"  结果: {result_2.message}")

        # AI继续决策...

    else:
        print("\nAI决策: 密度可接受,可以继续深挖")

    # AI可以根据结果继续决策...


# ---------------------------------------------------------------------------
# 示例4: 批量处理多个地区
# ---------------------------------------------------------------------------

async def example_batch_regions():
    """示例: 批量处理多个地区."""
    print("\n" + "="*70)
    print("示例4: 批量处理多个地区")
    print("="*70)

    # AI指定要处理的地区和参数
    targets = [
        {"region": "EUR", "universe": "TOP2500", "fields": ["close", "volume"]},
        {"region": "USA", "universe": "TOP3000", "fields": ["close", "volume"]},
        {"region": "CHN", "universe": "TOP3000", "fields": ["close", "volume"]},
    ]

    results = {}
    for target in targets:
        print(f"\n处理 {target['region']}/{target['universe']}...")

        field_specs = [
            FieldSpec(id=f, dataset_id="pv1", type="MATRIX", coverage=0.9)
            for f in target["fields"]
        ]

        result = await run_full_workflow(
            region=target["region"],
            universe=target["universe"],
            field_ids=target["fields"],
            field_specs=field_specs,
            execute=False
        )

        results[target["region"]] = result

        # AI解析结果
        if result.get("survey"):
            survey = result["survey"]
            print(f"  任务: {survey.tasks_generated}")
            if survey.top_templates:
                print(f"  Top模板密度: {survey.top_templates[0]['density']:.2f}")

    # AI可以比较不同地区的表现
    print("\n比较结果:")
    for region, result in results.items():
        if result.get("survey") and result["survey"].top_templates:
            density = result["survey"].top_templates[0]["density"]
            print(f"  {region}: 密度={density:.2f}")

    return results


# ---------------------------------------------------------------------------
# 示例5: 从平台动态获取字段
# ---------------------------------------------------------------------------

async def example_dynamic_fields():
    """示例: 从平台动态获取字段列表."""
    print("\n" + "="*70)
    print("示例5: 动态获取字段")
    print("="*70)

    # 如果不提供field_specs,API会自动查询平台
    # (需要安装alpha_machine并配置brain_client)

    try:
        result = await run_full_workflow(
            region="EUR",
            universe="TOP2500",
            dataset_id="pv1",  # 指定数据集
            sample_n=80,       # 采样80个字段
            execute=False
        )

        print(f"\n结果: {result['survey'].message}")

    except ImportError:
        print("\n提示: 需要安装alpha_machine才能动态获取字段")
        print("      或提供field_specs参数避免平台查询")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

async def main():
    """运行所有示例."""
    print("\n" + "="*70)
    print("AI调用示例 — Alpha Operator Framework")
    print("="*70)

    # 运行示例
    await example_precise_fields()
    await example_full_workflow()
    await example_ai_decision_loop()
    await example_batch_regions()
    await example_dynamic_fields()

    print("\n" + "="*70)
    print("所有示例完成!")
    print("="*70)

    print("\n关键点:")
    print("  1. 可以指定精确的字段列表(field_ids参数)")
    print("  2. 可以单次调用完成完整工作流(run_full_workflow)")
    print("  3. 结果是结构化的(WorkflowResult对象)")
    print("  4. AI可以根据结果决策下一步")
    print("  5. 支持dry-run先查看任务再决定是否执行")
    print("  6. 可以批量处理多个地区/数据集")


if __name__ == "__main__":
    asyncio.run(main())