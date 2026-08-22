"""Unit tests for 2D Decoupled Consensus Pruning Engine & Field Signal Profiling."""

import tempfile
from pathlib import Path
import pytest

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.distill.template_pruner import (
    evaluate_and_prune_templates_2d,
    analyze_field_signal_quality,
)
from alpha_operator_framework.platform.platform_simulator import PlatformAlphaResult


def test_single_field_failure_does_not_mislead_pruning():
    """验证单一噪声字段回测失败不会误杀良性模板 (防止字段误判)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "test_prune.db")

        # 构造同一个模板在仅 1 个字段 (noisy_field) 上的失败回测记录
        results = [
            PlatformAlphaResult(
                alpha_id="res_01",
                expression="ts_scale(group_rank(noisy_field, subindustry), 30)",
                is_valid=True,
                sharpe=-0.15,
                fitness=0.0,
                turnover=0.20,
            ),
            PlatformAlphaResult(
                alpha_id="res_02",
                expression="ts_scale(group_rank(noisy_field, subindustry), 30)",
                is_valid=True,
                sharpe=-0.10,
                fitness=0.0,
                turnover=0.20,
            ),
        ]

        # 执行二维剪枝评估 (共识门槛 min_distinct_fields=2)
        res = evaluate_and_prune_templates_2d(db, results, min_distinct_fields=2, min_sample_n=2)

        # 验证：未达到多字段共识门槛，不予剪枝
        assert len(res.pruned_patterns) == 0
        assert any("未达" in log or "保留观察" in log for log in res.audit_logs)


def test_gold_shield_immunity_prevents_pruning():
    """验证曾产出高夏普胜出因子的模板享有金牌豁免权，严防被误杀."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "test_prune.db")

        # 同一模板在 3 个不同字段上测试，其中 1 个产生了 1.45 的高夏普，另外 2 个表现较差
        results = [
            PlatformAlphaResult(alpha_id="r1", expression="ts_scale(group_rank(good_field, subindustry), 30)", is_valid=True, sharpe=1.45, fitness=1.2),
            PlatformAlphaResult(alpha_id="r2", expression="ts_scale(group_rank(bad_field_1, subindustry), 30)", is_valid=True, sharpe=-0.05, fitness=0.0),
            PlatformAlphaResult(alpha_id="r3", expression="ts_scale(group_rank(bad_field_2, subindustry), 30)", is_valid=True, sharpe=0.02, fitness=0.0),
        ]

        res = evaluate_and_prune_templates_2d(db, results, min_distinct_fields=2, min_sample_n=3)

        # 验证：获得豁免保护，绝对不予剪枝
        assert len(res.pruned_patterns) == 0
        assert len(res.immune_templates) >= 1
        assert any("豁免保护" in log for log in res.audit_logs)


def test_cross_field_consensus_prunes_true_defective_pattern():
    """验证跨多个不同字段全面失败的真正结构缺陷模板被正确共识淘汰."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = AlphaDatabase(Path(tmp) / "test_prune.db")

        # 缺陷结构：嵌套二次差分在 3 个不同字段上均严重亏损
        results = [
            PlatformAlphaResult(alpha_id="r1", expression="ts_delta(ts_delta(feat_a, 252), 500)", is_valid=True, sharpe=-0.35, fitness=0.0),
            PlatformAlphaResult(alpha_id="r2", expression="ts_delta(ts_delta(feat_b, 252), 500)", is_valid=True, sharpe=-0.25, fitness=0.0),
            PlatformAlphaResult(alpha_id="r3", expression="ts_delta(ts_delta(feat_c, 252), 500)", is_valid=True, sharpe=-0.40, fitness=0.0),
            PlatformAlphaResult(alpha_id="r4", expression="ts_delta(ts_delta(feat_d, 252), 500)", is_valid=True, sharpe=-0.30, fitness=0.0),
        ]

        res = evaluate_and_prune_templates_2d(db, results, min_distinct_fields=3, min_sample_n=3)

        # 验证：多字段共识达成，正确淘汰该模式并写入规则库
        assert len(res.pruned_patterns) >= 1
        assert any("ts_delta(ts_delta(" in p for p in res.pruned_patterns)


def test_field_signal_quality_profiling():
    """验证特征字段信号纯度画像能够准确识别纯白噪声字段与 Alpha 字段."""
    results = [
        # alpha_feat 在两个族中均表现优异
        {"alpha_id": "r1", "expression": "rank(alpha_feat)", "sharpe": 1.20, "family": "momentum"},
        {"alpha_id": "r2", "expression": "ts_scale(alpha_feat, 30)", "sharpe": 0.95, "family": "scaling"},
        # noise_feat 在 3 个不同族中全部为负收益
        {"alpha_id": "r3", "expression": "rank(noise_feat)", "sharpe": -0.20, "family": "momentum"},
        {"alpha_id": "r4", "expression": "-1 * rank(noise_feat)", "sharpe": -0.15, "family": "reversion"},
        {"alpha_id": "r5", "expression": "ts_scale(noise_feat, 30)", "sharpe": -0.10, "family": "scaling"},
    ]

    profiles = analyze_field_signal_quality(results, min_distinct_families=3)
    assert profiles["alpha_feat"].tier == "Alpha"
    assert profiles["alpha_feat"].is_noise is False
    assert profiles["noise_feat"].tier == "Noise"
    assert profiles["noise_feat"].is_noise is True
