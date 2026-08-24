"""Crash-recovery drill command adapter."""

from __future__ import annotations

import tempfile
from argparse import Namespace
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "alpha-factory.yaml"


def command_drill_recovery(args: Namespace) -> None:
    from alpha_operator_framework.application.research_cycle import ResearchCycleRequest
    from alpha_operator_framework.domain.evidence import EvidenceLevel, SubmissionApprovalEngine
    from alpha_operator_framework.experiment.models import BacktestResult
    from alpha_operator_framework.infrastructure.runtime_factory import build_research_runtime
    from alpha_operator_framework.research.round import Candidate, ResearchPolicy

    if getattr(args, "temp", True):
        config_path = Path(tempfile.mkdtemp()) / "alpha-factory.yaml"
        config_path.write_text("storage:\n  database_type: sqlite\n  driver: sqlite\n  connection_type: file\n  path: drill_research.db\nresearch:\n  execute_platform: true\n", encoding="utf-8")
    else:
        config_path = Path(getattr(args, "config", DEFAULT_CONFIG_PATH))
    policy = ResearchPolicy(region="GBR", universe="TOP700", max_backtests=2, policy_version="drill-v1", selection_strategy="diversity")
    candidates = [Candidate("drill_c1", "ts_rank(returns, 22)", "ts_momentum", ("returns",), ("ts_rank",), "template"), Candidate("drill_c2", "group_neutralize(rank(vwap), subindustry)", "mean_reversion", ("vwap",), ("rank", "group_neutralize"), "template")]

    class Gateway:
        def run_backtests(self, tasks):
            return [BacktestResult(task.task_id, task.expression, 1.72, 1.40, 0.18, 7.0, True, f"DRILL_ALPHA_{index:03d}") for index, task in enumerate(tasks, start=1)]

    round_id = "round_drill_recovery_001"
    initial = build_research_runtime(config_path, execute_platform=True, backtest_gateway=Gateway())
    initial.plan(ResearchCycleRequest(round_id, 42, policy, initial.knowledge_base.snapshot(), candidates, True))
    recovered = build_research_runtime(config_path, execute_platform=True, backtest_gateway=Gateway(), evidence_records={alpha_id: {"locked_oos_passed": True, "checks_passed": True, "correlation_passed": True, "oos_metrics": {"sharpe": 1.45}, "checks": [{"name": "LOW_SHARPE", "result": "PASS"}], "judge_verdict": "READY"} for alpha_id in ("DRILL_ALPHA_001", "DRILL_ALPHA_002")}, submission_authorized=True)
    summary = recovered.process_round(round_id)
    approval = SubmissionApprovalEngine.evaluate(alpha_id="DRILL_ALPHA_001", evidence_level=EvidenceLevel.PLATFORM_IS, is_metrics={"sharpe": 1.72, "fitness": 1.40, "turnover": 0.18, "margin": 7.0}, oos_metrics={"sharpe": 1.45}, checks=[{"name": "LOW_SHARPE", "result": "PASS"}], sc_value=0.25, pc_value=0.20, judge_verdict="READY")
    print(f"recovery drill: {summary.round_id} | completed_backtests={summary.completed_backtests} | approved={approval.approved}")
