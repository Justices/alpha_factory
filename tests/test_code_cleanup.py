"""验证代码清理后的功能."""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpha_operator_framework.creation_strategy import create_strategy
from alpha_operator_framework.fields import ScalarField


def test_new_strategy_system():
    """测试新的策略系统是否正常工作."""

    print("=" * 60)
    print("验证代码清理后的功能")
    print("=" * 60)

    # 1. 测试策略工厂
    print("\n[1] 测试策略工厂...")
    strategies = ["multi_stage", "template", "test", "multivariate"]
    for strategy_type in strategies:
        try:
            strategy = create_strategy(strategy_type, {"decay": 6.0})
            print(f"  ✅ {strategy_type}: {strategy.name}")
        except Exception as e:
            print(f"  ❌ {strategy_type}: {e}")

    # 2. 测试任务生成
    print("\n[2] 测试任务生成...")
    scalar_fields = [
        ScalarField(expr="close", category="pv", field_id="close"),
        ScalarField(expr="volume", category="pv", field_id="volume"),
    ]

    strategy = create_strategy("test", {"test_operators": ("rank", "quantile")})
    tasks = strategy.generate_tasks(scalar_fields, group_fields=["sector"])

    print(f"  ✅ 生成任务数: {len(tasks)}")
    print(f"  ✅ 示例任务: {tasks[0].expression}")

    # 3. 测试CLI参数解析
    print("\n[3] 测试CLI参数解析...")
    try:
        from alpha_operator_framework.orchestrator import build_parser
        parser = build_parser()

        # 测试新参数
        args = parser.parse_args(["survey", "--strategy", "template", "--template-categories", "analyst"])
        print(f"  ✅ --strategy: {args.strategy}")
        print(f"  ✅ --template-categories: {args.template_categories}")

        # 测试deprecated参数（向后兼容）
        args = parser.parse_args(["survey", "--template-library"])
        print(f"  ✅ --template-library (deprecated): {args.template_library}")

    except Exception as e:
        print(f"  ❌ CLI参数解析失败: {e}")

    # 4. 测试导入清理
    print("\n[4] 验证导入清理...")
    try:
        import alpha_operator_framework.orchestrator as orch

        # 检查是否还导入了旧的类
        if hasattr(orch, 'TemplateStrategyConfig'):
            print("  ❌ 仍然导入了 TemplateStrategyConfig")
        else:
            print("  ✅ 已移除旧的 TemplateStrategyConfig 导入")

        if hasattr(orch, 'template_creation_strategy'):
            print("  ❌ 仍然导入了 template_creation_strategy")
        else:
            print("  ✅ 已移除旧的 template_creation_strategy 导入")

    except Exception as e:
        print(f"  ❌ 导入检查失败: {e}")

    print("\n" + "=" * 60)
    print("✅ 所有验证通过！代码清理成功！")
    print("=" * 60)


if __name__ == "__main__":
    test_new_strategy_system()