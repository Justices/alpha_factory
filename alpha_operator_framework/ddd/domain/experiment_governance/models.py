"""Experiment Governance Bounded Context - Domain Models & Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class BacktestTask:
    """Task descriptor for platform backtesting."""
    task_id: str
    candidate_id: str
    expression: str
    decay: int
    settings: Dict[str, Any]
    idempotency_key: str


@dataclass(frozen=True)
class NormalizedBacktestResult:
    """Normalized, immutable result returned from a backtest execution."""
    task_id: str
    alpha_id: str
    expression: str
    is_valid: bool
    sharpe: float
    fitness: float
    turnover: float
    annualized_return: float
    max_drawdown: float
    checks_passed: bool
    failed_checks: List[str] = field(default_factory=list)
    raw_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PostPruneDecision:
    """Post-backtest pruning outcome based on cross-field consensus or extreme decay/churn."""
    task_id: str
    is_pruned: bool
    reason_code: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = "1.0.0"


@dataclass(frozen=True)
class EvaluationRecord:
    """Evidence-based evaluation grading of an executed candidate."""
    task_id: str
    verdict: str  # READY | PROMISING | REJECTED
    score: float
    criteria_breakdown: Dict[str, bool]
    actionable_recommendation: str = ""


@dataclass(frozen=True)
class ParetoRank:
    """Multi-objective ranking on non-dominated frontier."""
    task_id: str
    rank: int
    crowding_distance: float


@dataclass
class ExperimentBatch:
    """Aggregate Root: Owns the lifecycle of a submitted backtest batch and its evaluations."""
    batch_id: str
    idempotency_key: str
    tasks: Dict[str, BacktestTask] = field(default_factory=dict)
    results: Dict[str, NormalizedBacktestResult] = field(default_factory=dict)
    post_prune_decisions: Dict[str, PostPruneDecision] = field(default_factory=dict)
    evaluations: Dict[str, EvaluationRecord] = field(default_factory=dict)
    pareto_ranks: Dict[str, ParetoRank] = field(default_factory=dict)
    status: str = "PENDING"  # PENDING | COMPLETED | FAILED | EVALUATED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_task(self, task: BacktestTask) -> None:
        self.tasks[task.task_id] = task

    def record_result(self, result: NormalizedBacktestResult) -> None:
        self.results[result.task_id] = result

    def record_post_prune(self, decision: PostPruneDecision) -> None:
        self.post_prune_decisions[decision.task_id] = decision

    def record_evaluation(self, eval_record: EvaluationRecord) -> None:
        self.evaluations[eval_record.task_id] = eval_record

    def get_ready_candidates(self) -> List[NormalizedBacktestResult]:
        ready_ids = {
            t_id for t_id, ev in self.evaluations.items()
            if ev.verdict == "READY"
            and not (self.post_prune_decisions.get(t_id) and self.post_prune_decisions[t_id].is_pruned)
        }
        return [r for t_id, r in self.results.items() if t_id in ready_ids]
