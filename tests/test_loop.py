"""研究闭环编排 (loop) 单元测试 — P2 接入验证."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_run_round_survey_extracts_results():
    from alpha_operator_framework.loop import _run_round_survey, LoopConfig
    from alpha_operator_framework.ai_workflow import WorkflowResult

    config = LoopConfig(region="EUR", universe="TOP2500", rounds=1)
    with tempfile.TemporaryDirectory() as tmp:
        results_file = Path(tmp) / "results.json"
        results_file.write_text(json.dumps({
            "results": [{"expression": "rank(close)", "sharpe": 1.5}]
        }), encoding="utf-8")
        fake_survey = WorkflowResult(success=True, stage="survey", results_file=results_file)

        async def fake_aget(region, universe, delay, **kwargs):
            return [{"id": "close", "dataset": {"id": "pv1"}, "type": "MATRIX", "coverage": 0.9}]

        async def fake_run_survey(field_specs, config, execute=False, **kwargs):
            # 加权字段正确传入 survey_config
            assert config.field_ids == ["close"]
            assert config.template_families == LoopConfig.families
            assert execute is False
            return fake_survey

        with patch("alpha_operator_framework.cache.datafields.aget_datafields",
                   side_effect=fake_aget), \
             patch("alpha_operator_framework.ai_workflow.run_survey_with_fields",
                   side_effect=fake_run_survey):
            results = asyncio.run(_run_round_survey(config, 0, ["close"]))
        assert results == [{"expression": "rank(close)", "sharpe": 1.5}]


def test_run_round_survey_empty_field_ids_passes_none():
    from alpha_operator_framework.loop import _run_round_survey, LoopConfig
    from alpha_operator_framework.ai_workflow import WorkflowResult

    config = LoopConfig(region="EUR", universe="TOP2500")
    fake_survey = WorkflowResult(success=True, stage="survey")

    async def fake_aget(region, universe, delay, **kwargs):
        return [{"id": "close", "dataset": {"id": "pv1"}, "type": "MATRIX", "coverage": 0.9}]

    async def fake_run_survey(field_specs, config, execute=False, **kwargs):
        # 首轮空字段 → 传 None (全量采样)
        assert config.field_ids is None
        return fake_survey

    with patch("alpha_operator_framework.cache.datafields.aget_datafields",
               side_effect=fake_aget), \
         patch("alpha_operator_framework.ai_workflow.run_survey_with_fields",
               side_effect=fake_run_survey):
        results = asyncio.run(_run_round_survey(config, 0, []))
    assert results == []


def test_run_research_loop_closes_loop():
    from alpha_operator_framework.loop import LoopConfig, run_research_loop
    from alpha_operator_framework.database import AlphaDatabase

    config = LoopConfig(rounds=2, region="EUR", universe="TOP2500", distill_templates=True)
    fake_results = [
        {"expression": "rank(close)", "sharpe": 1.5, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
        {"expression": "rank(volume)", "sharpe": 1.2, "fitness": 1.0,
         "pnl": 5_000_000, "longCount": 60, "shortCount": 60},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        db = AlphaDatabase(str(Path(tmp) / "research.db"))
        try:
            with patch("alpha_operator_framework.loop._run_round_survey",
                       new=AsyncMock(return_value=fake_results)):
                history = asyncio.run(run_research_loop(db, config))

            assert len(history) == 2
            # 字段信号沉淀 (第6→1) 生效
            assert db.get_field_signal_stats(region="EUR")
            # 模板蒸馏回填 (第6→2) 生效
            assert db.list_templates(families=["distilled"])
            # 每轮记录含蒸馏骨架数
            assert all("distilled_templates" in h for h in history)
            assert history[0]["distilled_templates"] >= 1
        finally:
            db.close()
