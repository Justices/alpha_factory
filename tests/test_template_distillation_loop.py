"""Unit tests for autonomous template distillation and dynamic knowledge transfer closed-loop."""

import tempfile
from pathlib import Path
import pytest

from alpha_operator_framework.database import AlphaDatabase, TemplateRepository
from alpha_operator_framework.carpet_mining import StratifiedCarpetMiner, CarpetMiningConfig
from alpha_operator_framework.domain.judge.evaluator import JudgeReport, JudgeVerdict


def test_template_distillation_and_dynamic_instantiation_loop():
    """验证完整的胜出因子反向抽象 -> 自动入库 -> 跨数据集动态实例化的全闭环流程."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_distill_loop.db"
        db = AlphaDatabase(db_path)
        tpl_repo = TemplateRepository(db.manager)

        # 1. 模拟回测终审胜出因子
        winning_reports = [
            JudgeReport(
                alpha_id="alpha_win_01",
                expression="ts_scale(group_rank(est_fcf, subindustry), 30)",
                verdict=JudgeVerdict.READY,
                priority_score=90.0,
                platform_checks_passed=True,
                failed_checks=[],
                rubric_results=[],
                current_diversity_score=1.0,
                projected_diversity_delta=0.2,
                actionable_recommendations=[],
                metrics={"sharpe": 1.65, "fitness": 1.4, "turnover": 0.15, "annualized_return": 0.22, "max_drawdown": 0.05},
                family="mining",
            ),
            JudgeReport(
                alpha_id="alpha_win_02",
                expression="ts_zscore(group_rank(est_eps, subindustry), 63)",
                verdict=JudgeVerdict.READY,
                priority_score=85.0,
                platform_checks_passed=True,
                failed_checks=[],
                rubric_results=[],
                current_diversity_score=1.0,
                projected_diversity_delta=0.15,
                actionable_recommendations=[],
                metrics={"sharpe": 1.45, "fitness": 1.2, "turnover": 0.12, "annualized_return": 0.18, "max_drawdown": 0.06},
                family="mining",
            ),
        ]

        # 2. 挖掘器执行自主反向蒸馏 Hook
        config = CarpetMiningConfig(region="GBR", universe="TOP700", datasets=["test_dataset"], execute=False)
        miner = StratifiedCarpetMiner(config=config, db=db)
        distilled = miner.distill_and_persist_winning_templates(winning_reports)

        assert len(distilled) >= 2
        # 确认骨架中具体字段已去标识化为 {a} 槽位
        assert any("ts_scale(group_rank({a}, subindustry), 30)" in s for s in distilled)
        assert any("ts_zscore(group_rank({a}, subindustry), 63)" in s for s in distilled)

        # 3. 验证数据库中已成功沉淀模板
        active_tpls = tpl_repo.list_templates(active_only=True)
        evolved_tpls = [t for t in active_tpls if t.family == "evolved_distillation"]
        assert len(evolved_tpls) >= 2

        # 4. 模拟在全新数据集 (如 fundamental31) 上运行，验证动态从 DB 消费进化模板
        new_fields = [
            {"id": "gross_profit_margin", "dataset_id": "fundamental31", "type": "MATRIX"},
            {"id": "operating_cash_flow", "dataset_id": "fundamental31", "type": "MATRIX"},
        ]
        categorized = miner.generate_candidate_expressions_by_category(new_fields)
        assert "evolved_distillation" in categorized
        evolved_tasks = categorized["evolved_distillation"]
        assert len(evolved_tasks) >= 2

        # 验证新字段已被正确填入数据库进化模板
        evolved_expressions = [t.expression for t in evolved_tasks]
        assert any("gross_profit_margin" in e for e in evolved_expressions)
        assert any("operating_cash_flow" in e for e in evolved_expressions)
