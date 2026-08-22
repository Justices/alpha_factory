"""Unit tests for Dual-Axis Stratified Sampler (Field-Fairness Round-Robin & Coverage Guarantee)."""

import tempfile
from pathlib import Path
import pytest

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.carpet_mining import StratifiedCarpetMiner, CarpetMiningConfig, Task


def test_dual_axis_sampler_field_coverage_guarantee():
    """验证双轴抽样器能够消除字段饥饿，实现输入字段的高覆盖率与轮转保底."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_sampler.db"
        db = AlphaDatabase(db_path)

        # 模拟包含 10 个原子特征字段的数据集
        fields = [{"id": f"feature_{i:02d}", "dataset_id": "test_ds", "type": "MATRIX"} for i in range(10)]
        config = CarpetMiningConfig(
            region="GBR",
            universe="TOP700",
            datasets=["test_ds"],
            sample_per_family=2,  # 每类抽 2 条，10 类总共抽 20 条
            execute=False,
        )
        miner = StratifiedCarpetMiner(config=config, db=db)

        # 1. 生成候选池
        categorized = miner.generate_candidate_expressions_by_category(fields)
        assert len(categorized) >= 8

        # 2. 执行双轴抽样
        cohort = miner.sample_cohort(categorized)
        assert len(cohort) >= 16

        # 3. 统计抽样结果中的字段覆盖情况
        sampled_fields = set()
        for t in cohort:
            if t.meta and "field" in t.meta:
                sampled_fields.add(t.meta["field"])
            elif t.meta and "fields" in t.meta:
                for f in t.meta["fields"]:
                    sampled_fields.add(f)

        # 验证：10 个字段在 20 条总抽样中全部被公平轮转覆盖到 (100% 覆盖)
        for i in range(10):
            fid = f"feature_{i:02d}"
            assert fid in sampled_fields, f"字段 {fid} 遭遇饥饿遗漏！"


def test_dual_axis_sampler_untested_priority():
    """验证双轴抽样器在优先字段公平的同时，保持 100% 未测空间优先."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_untested.db"
        db = AlphaDatabase(db_path)

        fields = [
            {"id": "alpha_feat_01", "dataset_id": "test_ds", "type": "MATRIX"},
            {"id": "alpha_feat_02", "dataset_id": "test_ds", "type": "MATRIX"},
        ]
        config = CarpetMiningConfig(region="GBR", universe="TOP700", datasets=["test_ds"], sample_per_family=2, execute=False)
        miner = StratifiedCarpetMiner(config=config, db=db)
        categorized = miner.generate_candidate_expressions_by_category(fields)

        # 把部分表达式提前写入 DB 作为已回测历史
        some_task = categorized["ts_momentum"][0]
        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO alpha_expressions (expression_sha, expression, expression_origin, settings, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (db.compute_sha(some_task.expression), some_task.expression, "test", "{}", "completed")
            )

        cohort = miner.sample_cohort(categorized)
        cohort_shas = {db.compute_sha(t.expression) for t in cohort}

        # 验证提前标记为 completed 的表达式不会被优先抽取 (只要该分类还有未测候选)
        assert db.compute_sha(some_task.expression) not in cohort_shas
