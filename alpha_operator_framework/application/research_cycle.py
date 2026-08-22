"""Thin application orchestration for a research-round planning cycle."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from alpha_operator_framework.experiment.evaluation import evaluate_result
from alpha_operator_framework.experiment.models import ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.pruning import AstPrePruner
from alpha_operator_framework.research.round import Candidate, KnowledgeSnapshot, ResearchPolicy, ResearchRound
from alpha_operator_framework.research.selection import WeightedStratifiedSelector


@dataclass(frozen=True)
class ResearchCycleRequest:
    round_id: str
    seed: int
    policy: ResearchPolicy
    knowledge: KnowledgeSnapshot
    candidates: Sequence[Candidate]
    execute_platform: bool = False


@dataclass(frozen=True)
class ResearchCycleSummary:
    status: str
    round_id: str
    selection_audit: list[dict[str, object]]
    completed_backtests: int = 0
    knowledge_version: int = 0
    distilled_template_count: int = 0


class ResearchCycleUseCase:
    def __init__(
        self,
        research_repository: Any,
        backtest_gateway: Any,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        self.research_repository = research_repository
        self.backtest_gateway = backtest_gateway
        self.knowledge_base = knowledge_base or KnowledgeBase()

    def execute(self, request: ResearchCycleRequest) -> ResearchCycleSummary:
        round_ = ResearchRound(request.round_id, request.policy, request.seed, list(request.candidates))
        round_.pruning_decisions = AstPrePruner().evaluate(round_.candidates, request.policy)
        rejected = {decision.candidate_id for decision in round_.pruning_decisions if decision.rejected}
        round_.candidates = [candidate for candidate in round_.candidates if candidate.candidate_id not in rejected]
        decisions = round_.select(WeightedStratifiedSelector(), request.knowledge, random.Random(request.seed))
        self.research_repository.save_round(round_)
        audit = [
            {
                "candidate_id": decision.candidate_id,
                "selected": decision.selected,
                "reason": decision.reason,
                "score_components": dict(decision.score_components),
                "knowledge_version": request.knowledge.version,
                "seed": request.seed,
            }
            for decision in decisions
        ]
        if not request.execute_platform:
            return ResearchCycleSummary("PLANNED", round_.round_id, audit)

        selected_ids = {decision.candidate_id for decision in decisions if decision.selected}
        cohort = [candidate for candidate in round_.candidates if candidate.candidate_id in selected_ids]
        batch = ExperimentBatch(batch_id=round_.round_id, idempotency_key=round_.round_id)
        tasks = batch.create_tasks(cohort, request.policy)
        for result in self.backtest_gateway.run_backtests(tasks):
            batch.record_result(result)
            batch.record_evaluation(evaluate_result(result))
        templates = {
            task.task_id: next(candidate.template_id for candidate in cohort if candidate.candidate_id == task.candidate_id)
            for task in tasks
        }
        knowledge = self.knowledge_base.apply_batch(batch, templates)
        distilled_templates = self.knowledge_base.distill_batch(batch)
        return ResearchCycleSummary(
            "COMPLETED",
            round_.round_id,
            audit,
            completed_backtests=len(batch.results),
            knowledge_version=knowledge.version,
            distilled_template_count=len(distilled_templates),
        )
