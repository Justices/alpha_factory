"""Application Layer Summary & DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def validate_execution_flags(*, execute_platform: bool, authorize_submission: bool) -> None:
    """Reject unsafe execution combinations before any gateway is constructed."""
    if authorize_submission and not execute_platform:
        raise ValueError("--authorize-submission requires --execute")


@dataclass(frozen=True)
class ResearchCycleRequest:
    """Input request parameters for executing a research cycle round."""
    region: str = "GBR"
    universe: str = "TOP700"
    dataset_ids: Optional[List[str]] = None
    selection_algorithm: str = "stratified"  # stratified | d_optimal | thompson | ucb | nsga2
    sample_per_family: int = 4
    batch_size: int = 8
    decay: int = 12
    neutralization: str = "SUBINDUSTRY"
    execute_platform: bool = False  # False = dry-run, True = real platform submission
    authorize_submission: bool = False  # Explicit opt-in for platform alpha submission
    seed: int = 42


@dataclass
class ResearchCycleSummary:
    """Comprehensive, explainable summary of an executed research cycle."""
    round_id: str
    region: str
    universe: str
    selection_algorithm: str
    status: str
    total_fields: int = 0
    eligible_fields: int = 0
    candidates_generated: int = 0
    pre_pruned_rejected: int = 0
    candidates_selected: int = 0
    backtests_completed: int = 0
    post_pruned_count: int = 0
    ready_alphas_count: int = 0
    promising_alphas_count: int = 0
    submitted_alphas_count: int = 0
    distilled_templates_count: int = 0
    decisions_audit: List[Dict[str, Any]] = field(default_factory=list)
    audit_logs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def format_cli_report(self) -> str:
        lines = [
            "=" * 70,
            f"🚀 [Alpha Factory DDD Research Cycle Summary] - Round {self.round_id}",
            "=" * 70,
            f"• 目标市场: {self.region} / {self.universe}",
            f"• 抽样策略: {self.selection_algorithm}",
            f"• 特征字段: 总数 {self.total_fields} | 合格准入 {self.eligible_fields}",
            f"• 候选生成: {self.candidates_generated} 条",
            f"• 语法预剪枝: 淘汰 {self.pre_pruned_rejected} 条 (无效/重复)",
            f"• 策略入选: 选中 {self.candidates_selected} 条进入回测批次",
            f"• 回测完成: {self.backtests_completed} 条",
            f"• 二维共识后剪枝: 淘汰 {self.post_pruned_count} 条",
            f"• 6维证据裁决: READY {self.ready_alphas_count} 条 | PROMISING {self.promising_alphas_count} 条",
            f"• 平台正式提交: {self.submitted_alphas_count} 条",
            f"• 新增蒸馏模板: {self.distilled_templates_count} 个",
            "=" * 70,
        ]
        return "\n".join(lines)
