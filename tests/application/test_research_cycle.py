"""Application composition tests for the new research-round cycle."""

from __future__ import annotations

from alpha_operator_framework.application.research_cycle import ResearchCycleRequest, ResearchCycleUseCase
from alpha_operator_framework.experiment.models import BacktestResult
from alpha_operator_framework.infrastructure.brain import DryRunGateway
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy


class MemoryRepository:
    def __init__(self) -> None:
        self.round = None

    def save_round(self, round_) -> None:
        self.round = round_


def test_cycle_returns_replayable_planned_round_without_live_gateway() -> None:
    repository = MemoryRepository()
    use_case = ResearchCycleUseCase(repository, DryRunGateway())
    request = ResearchCycleRequest(
        round_id="round-1",
        seed=9,
        policy=ResearchPolicy("GBR", "TOP700", 1),
        knowledge=KnowledgeSnapshot(version=0),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=False,
    )

    summary = use_case.execute(request)

    assert summary.status == "PLANNED"
    assert summary.selection_audit
    assert repository.round.round_id == "round-1"


class CompletedGateway:
    def run_backtests(self, tasks):
        return [BacktestResult(tasks[0].task_id, tasks[0].expression, 1.5, 1.1, 0.2, 5.0, True, "alpha-1")]


def test_live_cycle_normalizes_results_and_updates_knowledge() -> None:
    repository = MemoryRepository()
    knowledge_base = KnowledgeBase()
    use_case = ResearchCycleUseCase(repository, CompletedGateway(), knowledge_base)
    request = ResearchCycleRequest(
        round_id="round-live",
        seed=9,
        policy=ResearchPolicy("GBR", "TOP700", 1),
        knowledge=knowledge_base.snapshot(),
        candidates=[Candidate("candidate", "rank(close)", "family", ("close",), ("rank",), "template")],
        execute_platform=True,
    )

    summary = use_case.execute(request)

    assert summary.status == "COMPLETED"
    assert summary.completed_backtests == 1
    assert summary.knowledge_version == 1
    assert summary.distilled_template_count == 1
    assert knowledge_base.field_scores["close"] > 0
