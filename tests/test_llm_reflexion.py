"""Unit tests for Phase 4 LLM Autonomous Reflexion Engine."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.platform.platform_simulator import PlatformAlphaResult
from alpha_operator_framework.research.idea_extractor import PaperIdea
from alpha_operator_framework.research.reflexion_engine import LLMReflexionEngine


def test_llm_reflexion_engine_fallback_and_parsing():
    """验证在无外部 LLM 时能安全降级并解析反思结果."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "test_refl.db"
        db = AlphaDatabase(db_path)
        engine = LLMReflexionEngine(db=db)

        fields = [
            {"id": "est_fcf", "type": "MATRIX", "description": "Free cash flow forecast"},
            {"id": "est_eps", "type": "MATRIX", "description": "Earnings per share forecast"},
        ]

        # 1. 自主假说生成 (降级运行)
        ideas = engine.generate_autonomous_hypotheses(fields, count=2)
        assert len(ideas) >= 2
        for idea in ideas:
            assert isinstance(idea, PaperIdea)
            assert "est_fcf" in idea.abstract_formula or "est_eps" in idea.abstract_formula

        # 2. 模拟失败并触发反思
        failed_results = [
            PlatformAlphaResult(
                alpha_id="alpha_failed_01",
                expression="rank(est_fcf)",
                status="COMPLETED",
                sharpe=-0.45,
                fitness=0.1,
                turnover=0.88,
                annualized_return=-0.05,
                max_drawdown=0.35,
            )
        ]

        critique, evolved = engine.reflect_and_reformulate(failed_results, ideas)
        assert isinstance(critique, str)
        assert isinstance(evolved, list)
