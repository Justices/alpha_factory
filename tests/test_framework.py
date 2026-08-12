#!/usr/bin/env python
"""
单元测试 — Alpha Operator Framework

测试核心模块:
  - operators: 算子库和工厂函数
  - families: 模板族生成
  - fields: 字段预处理
  - density: 因子密度评估
"""

import sys
from pathlib import Path

# 添加项目根目录到PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from alpha_operator_framework import (
    # 算子
    basic_ops, ts_ops, group_ops, vec_ops, extended_ops,
    ts_factory, first_order_factory,
    # 模板族
    UNARY_TEMPLATES, BINARY_TEMPLATES, TERNARY_TEMPLATES,
    unary_factory, binary_factory, ternary_factory,
    Task,
    # 字段
    FieldSpec, SampleSpec,
    preprocess_field, sample_scalar_expressions, load_local_field_specs,
    find_positive_negative_pairs, find_cap_pairs, semantic_pair_task_factory,
    # 密度
    SignalGate, compute_density, top_templates,
    # 剪枝
    classify_field, extract_field_ids,
    semantic_prune_fields, SemanticPruneConfig,
    field_topk_prune, FieldTopKConfig,
)


def test_operators():
    """测试算子库."""
    print("测试算子库...")

    # 基础检查
    assert len(basic_ops) == 6, f"basic_ops应有6个, 实际{len(basic_ops)}"
    assert len(ts_ops) >= 10, f"ts_ops应至少10个, 实际{len(ts_ops)}"
    assert len(group_ops) == 3, f"group_ops应有3个, 实际{len(group_ops)}"
    assert vec_ops == [
        "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "vec_count"
    ], f"VEC算子集合不正确: {vec_ops}"

    # ts_factory测试
    exprs = ts_factory("ts_rank", "close", windows=[5, 22])
    assert len(exprs) == 2, f"应生成2个表达式, 实际{len(exprs)}"
    assert exprs[0] == "ts_rank(close, 5)", f"第一个表达式应为'ts_rank(close, 5)', 实际'{exprs[0]}'"

    # first_order_factory测试
    exprs = first_order_factory(["close"], ["rank", "ts_rank"])
    assert len(exprs) > 0, "应生成至少1个表达式"

    print("✓ 算子库测试通过")


def test_families():
    """测试模板族."""
    print("测试模板族...")

    # 常量检查
    assert len(UNARY_TEMPLATES) == 10, f"一元模板应有10个, 实际{len(UNARY_TEMPLATES)}"
    assert len(BINARY_TEMPLATES) == 8, f"二元模板应有8个, 实际{len(BINARY_TEMPLATES)}"
    assert len(TERNARY_TEMPLATES) == 7, f"三元模板应有7个, 实际{len(TERNARY_TEMPLATES)}"

    # Task数据结构测试
    task = Task(
        expression="rank(close)",
        template_index=0,
        family="unary",
        fields_per_alpha=1,
        decay=6.0
    )
    assert task.to_sim_dict() == {"expression": "rank(close)", "decay": 6.0}

    # unary_factory测试
    scalars = ["close", "volume"]
    tasks = unary_factory(scalars)
    assert len(tasks) == 20, f"2字段×10模板应生成20个任务, 实际{len(tasks)}"

    # binary_factory测试
    tasks = binary_factory(scalars)
    assert len(tasks) == 8, f"1对×8模板应生成8个任务, 实际{len(tasks)}"

    # ternary_factory测试
    scalars3 = ["close", "volume", "returns"]
    tasks = ternary_factory(scalars3)
    assert len(tasks) == 7, f"1三元组×7模板应生成7个任务, 实际{len(tasks)}"

    print("✓ 模板族测试通过")


def test_fields():
    """测试字段处理."""
    print("测试字段处理...")

    # FieldSpec测试
    field = FieldSpec(
        id="close",
        dataset_id="pv1",
        type="MATRIX",
        coverage=0.95,
        user_count=300
    )
    assert field.id == "close"
    assert field.type == "MATRIX"

    # preprocess_field测试 (MATRIX)
    exprs = preprocess_field(field)
    assert len(exprs) == 1, f"MATRIX字段应生成1个表达式, 实际{len(exprs)}"
    assert "winsorize(ts_backfill(close, 120)" in exprs[0]

    # preprocess_field测试 (VECTOR)
    vec_field = FieldSpec(
        id="sentiment",
        dataset_id="nws82",
        type="VECTOR",
        coverage=0.80
    )
    exprs = preprocess_field(vec_field)
    assert len(exprs) == len(vec_ops), f"VECTOR字段应为每个VEC算子生成表达式, 实际{len(exprs)}"

    # sample_scalar_expressions测试
    fields = [field, vec_field]
    spec = SampleSpec(sample_n=10, seed=42)
    scalars = sample_scalar_expressions(fields, spec)
    assert len(scalars) == 1 + len(vec_ops), f"应生成MATRIX与全部VEC归约表达式, 实际{len(scalars)}"

    print("✓ 字段处理测试通过")


def test_local_field_files():
    """测试本地 CSV / JSON 字段文件读取和研究设置预筛选。"""
    print("测试本地字段文件...")

    fixture_dir = ROOT / "tests" / "fixtures"
    csv_fields = load_local_field_specs(
        fixture_dir / "local_fields.csv", region="GBR", universe="TOP700", delay=1
    )
    assert len(csv_fields) == 1
    assert csv_fields[0].id == "act_12m_cps_value"
    assert csv_fields[0].dataset_id == "analyst7"
    assert csv_fields[0].coverage == 0.1642

    json_fields = load_local_field_specs(
        fixture_dir / "local_fields.json", region="GBR", universe="TOP700", delay=1,
        dataset_id="acquisition_model", data_type="VECTOR",
    )
    assert len(json_fields) == 1
    assert json_fields[0].id == "country_percentile_acquisition_likelihood"
    assert json_fields[0].type == "VECTOR"
    assert load_local_field_specs(fixture_dir / "local_fields.json", region="EUR") == []

    print("✓ 本地字段文件测试通过")


def test_semantic_pairs():
    """测试正负字段配对和同前缀 cap 归一化。"""
    print("测试语义二元配对...")
    fields = [
        FieldSpec(id="earnings_positive", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="earnings_negative", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="abc_revenue", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="abc_cap", dataset_id="d1", type="MATRIX"),
        FieldSpec(id="other_positive", dataset_id="d2", type="MATRIX"),
        FieldSpec(id="other_negative", dataset_id="d3", type="MATRIX"),
    ]
    assert [(a.id, b.id) for a, b in find_positive_negative_pairs(fields)] == [
        ("earnings_positive", "earnings_negative")
    ]
    assert [(a.id, b.id) for a, b in find_cap_pairs(fields)] == [("abc_revenue", "abc_cap")]
    tasks = semantic_pair_task_factory(fields)
    assert len(tasks) == 2
    assert any(" - " in task.expression and task.meta["pair_type"] == "polarity" for task in tasks)
    assert any(" / " in task.expression and task.meta["pair_type"] == "cap_ratio" for task in tasks)
    print("✓ 语义二元配对测试通过")


def test_density():
    """测试密度评估."""
    print("测试密度评估...")

    # SignalGate测试
    gate = SignalGate()
    row = {
        "sharpe": 1.5,
        "fitness": 1.2,
        "pnl": 5e6,
        "longCount": 60,
        "shortCount": 60
    }
    is_signal, snap = gate.is_signal(row)
    assert is_signal, "应判定为信号"
    assert snap["sharpe"] == 1.5

    # 非信号测试
    row_fail = {"sharpe": 0.5, "fitness": 0.3, "pnl": 1e5, "longCount": 30, "shortCount": 30}
    is_signal, _ = gate.is_signal(row_fail)
    assert not is_signal, "应判定为非信号"

    # compute_density测试
    results = [
        {
            "expression": "rank(close)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            **row
        },
        {
            "expression": "rank(volume)",
            "family": "unary",
            "template_index": 0,
            "source_freq": "unknown",
            "fields_per_alpha": 1,
            **row_fail
        }
    ]
    density_rows = compute_density(results, gate)
    assert len(density_rows) == 1, f"应聚合为1个密度行, 实际{len(density_rows)}"
    assert density_rows[0].density == 0.5, f"密度应为0.5, 实际{density_rows[0].density}"

    # top_templates测试
    top = top_templates(density_rows, top_n=1)
    assert len(top) == 1
    assert top[0].template_index == 0

    print("✓ 密度评估测试通过")


def test_pruning():
    """测试三阶段剪枝 (纯函数部分, 离线; correlation_prune 网络路径不在此测)."""
    print("测试剪枝模块...")

    # --- classify_field ---
    f_market = FieldSpec(id="close", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=5)
    f_analyst = FieldSpec(id="analyst4_fy1", dataset_id="analyst4", type="MATRIX", coverage=0.8)
    f_other = FieldSpec(id="xyz_abc", dataset_id="zzz123", type="MATRIX", coverage=0.5)
    assert classify_field(f_market) == "market", f"close/pv1应归market, 实际{classify_field(f_market)}"
    assert classify_field(f_analyst) == "analyst", f"analyst4_fy1应归analyst, 实际{classify_field(f_analyst)}"
    assert classify_field(f_other) == "other", f"未知字段应归other, 实际{classify_field(f_other)}"

    # --- semantic_prune_fields (冷门优先) ---
    fields = [
        # market: 3个 (user_count 5/1/3)
        f_market,                                          # user_count=5
        FieldSpec(id="volume", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=1),
        FieldSpec(id="returns", dataset_id="pv1", type="MATRIX", coverage=0.9, user_count=3),
        # analyst: 3个
        f_analyst,
        FieldSpec(id="analyst4_fy2", dataset_id="analyst4", type="MATRIX", coverage=0.8, user_count=2),
        FieldSpec(id="target_price", dataset_id="analyst4", type="MATRIX", coverage=0.8, user_count=4),
        # GROUP字段应被跳过
        FieldSpec(id="group_field", dataset_id="g1", type="GROUP", coverage=0.9, user_count=1),
    ]
    kept, pruned = semantic_prune_fields(
        fields, SemanticPruneConfig(keep_per_category=2))
    assert len(kept) == 4, f"2类×每类2个应留4个, 实际{len(kept)}"
    assert len(pruned) == 2, f"应剪掉2个, 实际{len(pruned)}"
    # 冷门优先: market类留 user_count 最低的 volume(1)和 returns(3), close(5)被剪
    kept_market = {f.id for f in kept if classify_field(f) == "market"}
    assert kept_market == {"volume", "returns"}, f"冷门优先失败, kept_market={kept_market}"
    assert all(p["category"] in ("market", "analyst") for p in pruned), "剪掉字段应带category"

    # --- extract_field_ids ---
    assert extract_field_ids("winsorize(ts_backfill(analyst4_fy1, 120), std=4)") == {"analyst4_fy1"}
    assert extract_field_ids("winsorize(ts_backfill(vec_avg(close), 120), std=4)") == {"close"}
    assert extract_field_ids("winsorize(rank(close, 5), std=4)") == {"__no_field__"}

    # --- field_topk_prune (每字段留最高sharpe) ---
    rows = [
        {"alpha_id": "a1", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.5},
        {"alpha_id": "a2", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.2},
        {"alpha_id": "a3", "expression": "winsorize(ts_backfill(volume, 120), std=4)", "sharpe": 1.4},
        {"alpha_id": "a4", "expression": "winsorize(ts_backfill(volume, 120), std=4)", "sharpe": 1.1},
    ]
    kept_rows, pruned_rows = field_topk_prune(rows, FieldTopKConfig(keep_per_field=1))
    assert {r["alpha_id"] for r in kept_rows} == {"a1", "a3"}, \
        f"每字段应留sharpe最高者, 实际{ {r['alpha_id'] for r in kept_rows} }"
    assert len(pruned_rows) == 2, f"应剪掉2个, 实际{len(pruned_rows)}"
    pruned_reasons = {r["prune_reason"] for r in pruned_rows}
    assert "same_field_topk:close" in pruned_reasons and "same_field_topk:volume" in pruned_reasons, \
        f"prune_reason缺失, 实际{pruned_reasons}"

    # --- field_topk_prune 正负方向分开 (split_by_sign=True) ---
    rows_sign = [
        {"alpha_id": "p1", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.6},   # +close
        {"alpha_id": "p2", "expression": "winsorize(ts_backfill(close, 120), std=4)", "sharpe": 1.2},   # +close (剪)
        {"alpha_id": "n1", "expression": "-winsorize(ts_backfill(close, 120), std=4)", "sharpe": -1.5}, # -close
        {"alpha_id": "n2", "expression": "-winsorize(ts_backfill(close, 120), std=4)", "sharpe": -1.1},# -close (剪)
    ]
    kept2, pruned2 = field_topk_prune(rows_sign, FieldTopKConfig(keep_per_field=1, split_by_sign=True))
    assert {r["alpha_id"] for r in kept2} == {"p1", "n1"}, \
        f"正负方向应分开计数, 保留p1/n1, 实际{ {r['alpha_id'] for r in kept2} }"
    assert {r["alpha_id"] for r in pruned2} == {"p2", "n2"}
    # 验证 prune_reason 带 "-close" 符号
    assert any("-close" in r.get("prune_reason", "") for r in pruned2), pruned2

    print("✓ 剪枝测试通过")


def run_all_tests():
    """运行所有测试."""
    print("\n" + "="*70)
    print("Alpha Operator Framework 单元测试")
    print("="*70 + "\n")

    try:
        test_operators()
        test_families()
        test_fields()
        test_local_field_files()
        test_semantic_pairs()
        test_density()
        test_pruning()

        print("\n" + "="*70)
        print("✓ 所有测试通过!")
        print("="*70 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}\n")
        return 1
    except Exception as e:
        print(f"\n✗ 测试异常: {e}\n")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(run_all_tests())
