"""测试创建策略组件."""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_operator_framework.creation_strategy import (
    create_strategy,
    MultiStageStrategy,
    TemplateStrategy,
    TestStrategy,
    CompositeStrategy,
    CompositeConfig,
)
from alpha_operator_framework.fields import ScalarField


def test_strategies():
    """测试不同策略的任务生成."""

    # 模拟标量字段数据
    scalar_fields = [
        ScalarField(expr="close", category="pv", field_id="close"),
        ScalarField(expr="volume", category="pv", field_id="volume"),
        ScalarField(expr="analyst_rating", category="analyst", field_id="analyst_rating"),
    ]
    group_fields = ["sector", "industry"]

    print("=" * 60)
    print("测试创建策略组件")
    print("=" * 60)

    # 1. 测试多阶工厂策略
    print("\n[1] 多阶工厂策略 (MultiStage)")
    print("-" * 60)
    strategy = create_strategy("multi_stage", {
        "include_first_order": True,
        "include_unary_template": True,
        "first_order_ops": ("rank", "zscore"),
        "decay": 6.0,
    })
    tasks = strategy.generate_tasks(scalar_fields)
    print(f"生成任务数: {len(tasks)}")
    if tasks:
        print(f"示例任务: {tasks[0].expression}")

    # 2. 测试模板库策略
    print("\n[2] 模板库策略 (Template)")
    print("-" * 60)
    strategy = create_strategy("template", {
        "families": ("unary", "binary"),
        "template_categories": ("pv",),
        "all_combinations": False,
        "sample_n": 5,
        "decay": 6.0,
    })
    # 模拟空模板列表（实际使用时从数据库加载）
    tasks = strategy.generate_tasks(scalar_fields, group_fields, templates=[])
    print(f"生成任务数: {len(tasks)}")
    print("（注: 需要数据库模板库才能生成实际任务）")

    # 3. 测试测试策略
    print("\n[3] 测试策略 (Test)")
    print("-" * 60)
    strategy = create_strategy("test", {
        "test_operators": ("rank", "quantile"),
        "quantile_bins": (5, 10),
        "include_neutralize": True,
        "decay": 6.0,
    })
    tasks = strategy.generate_tasks(scalar_fields, group_fields)
    print(f"生成任务数: {len(tasks)}")
    if tasks:
        print("\n示例任务:")
        for i, task in enumerate(tasks[:5]):
            print(f"  {i+1}. {task.expression} (test_type={task.meta.get('test_type')})")

    # 4. 测试多元字段策略
    print("\n[4] 多元字段策略 (Multivariate)")
    print("-" * 60)
    strategy = create_strategy("multivariate", {
        "min_fields": 2,
        "max_fields": 3,
        "cross_category": False,
        "combination_limit": 10,
        "decay": 6.0,
    })
    tasks = strategy.generate_tasks(scalar_fields)
    print(f"生成任务数: {len(tasks)}")
    if tasks:
        print(f"示例任务: {tasks[0].expression}")

    # 5. 测试组合策略
    print("\n[5] 组合策略 (Composite)")
    print("-" * 60)
    strategies = [
        create_strategy("multi_stage", {
            "include_first_order": True,
            "include_unary_template": False,
            "first_order_ops": ("rank",),
        }),
        create_strategy("test", {
            "test_operators": ("quantile",),
            "quantile_bins": (10,),
        }),
    ]
    composite = CompositeStrategy(strategies, CompositeConfig(mode="parallel"))
    tasks = composite.generate_tasks(scalar_fields)
    print(f"生成任务数: {len(tasks)}")
    if tasks:
        print(f"示例任务: {tasks[0].expression}")

    print("\n" + "=" * 60)
    print("✅ 所有策略测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    test_strategies()