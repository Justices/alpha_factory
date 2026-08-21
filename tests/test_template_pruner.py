"""模板蒸馏淘汰 (template_pruner) 单元测试."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.distill.template_pruner import (
    deactivate_noisy_templates,
    prune_templates_by_density,
    matches_prune_rule,
    prune_expression_candidates,
    seed_default_prune_rules,
    distill_prune_rules_from_density,
    _template_to_pattern,
)


def _seeded_db():
    """建临时库并 seed 4 族模板, 返回 db (调用方负责 close)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    import os
    os.close(fd)
    db = AlphaDatabase(path)
    db.seed_template_library()
    return db, path


def test_deactivate_noisy_templates_removes_nested_ts_delta():
    db, path = _seeded_db()
    try:
        before = db.list_templates(families=("unary",))
        assert len(before) == 10  # unary 族 10 个模板

        removed = deactivate_noisy_templates(db)

        # 嵌套 ts_delta 的: 增长率二阶(idx=1) + 差分层叠(idx=9) → 2 个
        assert len(removed) == 2, removed
        assert all(n.startswith("unary_") for n in removed)

        # active_only 查询不再返回被淘汰的
        after = db.list_templates(families=("unary",))
        assert len(after) == 8
        remaining_exprs = [t.expression_template for t in after]
        assert all(not e.startswith("ts_delta(ts_delta(") for e in remaining_exprs)

        # 幂等: 再次淘汰无新增
        assert deactivate_noisy_templates(db) == []
    finally:
        db.close()
        import os
        try:
            os.remove(path)
        except Exception:
            pass


def test_deactivate_templates_repository_supports_family():
    db, path = _seeded_db()
    try:
        # 直接按 family 淘汰 unary 全部
        n = db.deactivate_templates(family="unary")
        assert n == 10
        assert db.list_templates(families=("unary",)) == []
    finally:
        db.close()
        import os
        try:
            os.remove(path)
        except Exception:
            pass


def test_prune_templates_by_density_deactivates_zero_signal():
    db, path = _seeded_db()
    try:
        # 模拟 density 数据: binary idx=0 被充分采样但零信号
        density_rows = [
            {"family": "binary", "template_index": 0, "sample_n": 5, "density": 0.0},
            {"family": "binary", "template_index": 1, "sample_n": 3, "density": 0.4},
            {"family": "binary", "template_index": 2, "sample_n": 0, "density": 0.0},  # 未采样
        ]
        removed = prune_templates_by_density(db, density_rows, min_density=0.0, min_sample_n=1)
        # 只淘汰 idx=0 (零信号且被采样); idx=1 有密度保留; idx=2 未采样不淘汰
        assert removed == ["binary_0"], removed
    finally:
        db.close()
        import os
        try:
            os.remove(path)
        except Exception:
            pass


def test_matches_prune_rule_types():
    prefix_rule = {"pattern": "ts_delta(ts_delta(", "pattern_type": "prefix"}
    assert matches_prune_rule("ts_delta(ts_delta(close, 252), 500)", prefix_rule)
    assert not matches_prune_rule("ts_delta(close, 252)", prefix_rule)

    substr_rule = {"pattern": "signed_power", "pattern_type": "substring"}
    assert matches_prune_rule("ts_mean(signed_power(x, 2), 500)", substr_rule)
    assert not matches_prune_rule("ts_mean(x, 500)", substr_rule)

    import re
    regex_rule = {"pattern": r"^log\(abs\(", "pattern_type": "regex"}
    assert matches_prune_rule("log(abs(ts_delta(x, 500)))", regex_rule)
    assert not matches_prune_rule("ts_delta(x, 500)", regex_rule)


def test_prune_expression_candidates_filters_variants():
    rule = {"pattern": "ts_delta(ts_delta(", "pattern_type": "prefix"}
    exprs = [
        "rank(close)",
        "ts_delta(ts_delta(close, 252), 500)",
        "ts_delta(close, 5)",
        "ts_delta(ts_delta(volume, 252)/ts_delay(volume, 252), 252)",
    ]
    kept = prune_expression_candidates(exprs, [rule])
    assert kept == ["rank(close)", "ts_delta(close, 5)"]


def test_seed_default_prune_rules_idempotent():
    db, path = _seeded_db()
    try:
        assert seed_default_prune_rules(db) == 1
        # 幂等: 重复 seed 不新增
        assert seed_default_prune_rules(db) == 1
        rules = db.get_prune_rules()
        assert len(rules) == 1
        assert rules[0]["pattern"] == "ts_delta(ts_delta("
    finally:
        db.close()
        import os
        try:
            os.remove(path)
        except Exception:
            pass


def test_template_to_pattern_extracts_operator_prefix():
    assert _template_to_pattern("ts_delta(ts_delta({a}, 252), 500)") == "ts_delta(ts_delta("
    assert _template_to_pattern("ts_delta(ts_delta({a},252)/ts_delay({a},252), 252)") == "ts_delta(ts_delta("
    # 无占位符 (fixed) → 完整表达式
    assert _template_to_pattern("rank(close)") == "rank(close)"


def test_distill_prune_rules_from_density_skips_first_order():
    db, path = _seeded_db()
    try:
        # density 数据: unary 模板 idx=9 零信号 (应生成规则); 一阶算子 idx=9 零信号 (应跳过)
        density_rows = [
            {"family": "unary", "template_index": 9, "expression_origin": "unary_template",
             "sample_n": 5, "density": 0.0},
            {"family": "unary", "template_index": 9, "expression_origin": "first_order",
             "sample_n": 5, "density": 0.0},  # 一阶算子, 应跳过
            {"family": "unary", "template_index": 0, "expression_origin": "unary_template",
             "sample_n": 5, "density": 0.3},  # 有密度, 保留
        ]
        written = distill_prune_rules_from_density(db, density_rows, min_density=0.0, min_sample_n=1)
        # 只从 unary idx=9 模板 (差分层叠) 提取前缀规则
        assert written == ["ts_delta(ts_delta("], written
        # 规则库里有 source='distilled' 的规则
        distilled = db.get_prune_rules(source="distilled")
        assert len(distilled) == 1
        assert distilled[0]["pattern"] == "ts_delta(ts_delta("
    finally:
        db.close()
        import os
        try:
            os.remove(path)
        except Exception:
            pass
