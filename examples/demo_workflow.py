#!/usr/bin/env python
"""
示例: 使用Alpha Operator Framework进行因子研究

本示例展示完整的三段工作流:
  1. Survey: 调研EUR市场, 采样80组合
  2. Deepen: 深挖top-3模板
  3. Submit: 列出候选

注意:
  - 本示例为dry-run, 不消耗回测额度
  - 实际使用需先配置 alpha_machine 和 brain_client
"""

import sys
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 确保可以导入项目模块
import os
os.chdir(ROOT)

from alpha_operator_framework import (
    # 模板族
    UNARY_TEMPLATES, BINARY_TEMPLATES, TERNARY_TEMPLATES,
    unary_factory, binary_factory, ternary_factory,
    # 算子
    basic_ops, ts_ops, group_ops,
    first_order_factory, second_order_factory,
    # 密度评估
    SignalGate, compute_density, top_templates,
    # 字段处理
    FieldSpec, SampleSpec, sample_scalar_expressions,
)


def demo_templates():
    """演示模板族生成."""
    print("\n" + "="*70)
    print("1. 模板族概览")
    print("="*70)

    print(f"\n一元模板: {len(UNARY_TEMPLATES)} 个")
    for idx, template, rationale, fpa in UNARY_TEMPLATES[:3]:
        print(f"  [{idx}] {template[:60]}...  // {rationale}")

    print(f"\n二元模板: {len(BINARY_TEMPLATES)} 个")
    for idx, template, rationale, fpa in BINARY_TEMPLATES[:3]:
        print(f"  [{idx}] {template[:60]}...  // {rationale}")

    print(f"\n三元模板: {len(TERNARY_TEMPLATES)} 个")
    for idx, template, rationale, fpa in TERNARY_TEMPLATES[:3]:
        print(f"  [{idx}] {template[:60]}...  // {rationale}")


def demo_operators():
    """演示算子库."""
    print("\n" + "="*70)
    print("2. 算子库")
    print("="*70)

    print(f"\n基础算子: {basic_ops}")
    print(f"时间序列算子: {ts_ops[:5]}...")
    print(f"分组算子: {group_ops}")

    # 生成时间序列表达式
    print("\n示例: 对close字段应用ts_rank算子")
    exprs = first_order_factory(["close"], ["ts_rank"])
    for expr in exprs[:3]:
        print(f"  {expr}")


def demo_fields():
    """演示字段处理."""
    print("\n" + "="*70)
    print("3. 字段处理")
    print("="*70)

    # 构造模拟字段
    fields = [
        FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.95, user_count=300),
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.92, user_count=200),
        FieldSpec(id="sentiment", dataset_id="nws82", type="VECTOR", coverage=0.80, user_count=50),
    ]

    print(f"\n输入字段: {len(fields)} 个")
    for f in fields:
        print(f"  {f.id} ({f.type}) coverage={f.coverage:.2f} userCount={f.user_count}")

    # 采样
    spec = SampleSpec(sample_n=10, min_coverage=0.5, prefer_cold=True, seed=42)
    scalars = sample_scalar_expressions(fields, spec)

    print(f"\n采样结果: {len(scalars)} 个标量表达式")
    for expr in scalars[:3]:
        print(f"  {expr}")


def demo_task_generation():
    """演示任务生成."""
    print("\n" + "="*70)
    print("4. 任务生成")
    print("="*70)

    # 模拟标量字段
    scalars = ["winsorize(ts_backfill(close, 120), std=4)"]

    # 一元任务
    tasks = unary_factory(scalars)
    print(f"\n一元任务: {len(tasks)} 个")
    print(f"  示例: {tasks[0].expression}")

    # 二元任务 (需要至少2个字段)
    scalars2 = [
        "winsorize(ts_backfill(close, 120), std=4)",
        "winsorize(ts_backfill(volume, 120), std=4)"
    ]
    tasks = binary_factory(scalars2, max_pairs=1)
    print(f"\n二元任务: {len(tasks)} 个")
    print(f"  示例: {tasks[0].expression}")


def demo_density():
    """演示密度计算."""
    print("\n" + "="*70)
    print("5. 因子密度评估")
    print("="*70)

    # 模拟结果
    results = [
        {
            "expression": "ts_rank(close, 5)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            "sharpe": 1.5,
            "fitness": 1.2,
            "pnl": 5e6,
            "longCount": 60,
            "shortCount": 60
        },
        {
            "expression": "ts_rank(volume, 5)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            "sharpe": 0.5,
            "fitness": 0.3,
            "pnl": 1e5,
            "longCount": 30,
            "shortCount": 30
        }
    ]

    gate = SignalGate()
    rows = compute_density(results, gate)

    print(f"\n密度计算结果:")
    for r in rows:
        print(f"  [{r.family}/{r.template_index}] density={r.density:.2f} "
              f"sample={r.sample_n} signal={r.signal_n}")

    top = top_templates(rows, top_n=1)
    print(f"\nTop-1: [{top[0].family}/{top[0].template_index}] density={top[0].density:.2f}")


def main():
    """运行所有演示."""
    print("\n" + "="*70)
    print("Alpha Operator Framework 示例")
    print("="*70)

    demo_templates()
    demo_operators()
    demo_fields()
    demo_task_generation()
    demo_density()

    print("\n" + "="*70)
    print("演示完成!")
    print("="*70)
    print("\n下一步:")
    print("  1. 配置 alpha_machine 和 brain_client")
    print("  2. 运行 survey 阶段:")
    print("     python -m alpha_operator_framework.orchestrator survey --region EUR --execute")
    print("  3. 运行 deepen 阶段:")
    print("     python -m alpha_operator_framework.orchestrator deepen --density-out runs/survey_density.json --execute")
    print("  4. 列出候选:")
    print("     python -m alpha_operator_framework.orchestrator submit --kept-out runs/deepen_kept.json")
    print()


if __name__ == "__main__":
    main()