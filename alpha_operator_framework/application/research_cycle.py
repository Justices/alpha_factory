"""Thin application orchestration for a research-round planning cycle."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Sequence

from alpha_operator_framework.experiment.evaluation import evaluate_batch
from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import ExperimentBatch, MutationProposal
from alpha_operator_framework.experiment.mutation import propose_mutations
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.pruning import AstPrePruner
from alpha_operator_framework.research.policy import build_selector
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
    mutation_proposals: list[MutationProposal] = field(default_factory=list)


class ResearchCycleUseCase:
    def __init__(
        self,
        research_repository: Any,
        backtest_gateway: Any,
        knowledge_base: KnowledgeBase | None = None,
        experiment_repository: Any | None = None,
        telemetry: Any | None = None,
    ) -> None:
        self.research_repository = research_repository
        self.backtest_gateway = backtest_gateway
        self.knowledge_base = knowledge_base or KnowledgeBase()
        self.experiment_repository = experiment_repository
        self.telemetry = telemetry

    def _save_batch(self, batch: ExperimentBatch) -> None:
        if self.experiment_repository is not None:
            self.experiment_repository.save_batch(batch)

    def _transition(self, batch: ExperimentBatch, target: BatchState) -> None:
        event = transition(batch, target)
        if self.telemetry is not None:
            self.telemetry.record_transition(batch, event)
        self._save_batch(batch)

    def execute(self, request: ResearchCycleRequest) -> ResearchCycleSummary:
        round_ = ResearchRound(request.round_id, request.policy, request.seed, list(request.candidates))
        round_.pruning_decisions = AstPrePruner().evaluate(round_.candidates, request.policy)
        if self.telemetry is not None:
            for decision in round_.pruning_decisions:
                if decision.rejected:
                    self.telemetry.record_pruning_reason(decision.reason_code)
        rejected = {decision.candidate_id for decision in round_.pruning_decisions if decision.rejected}
        round_.candidates = [candidate for candidate in round_.candidates if candidate.candidate_id not in rejected]
        decisions = round_.select(build_selector(request.policy), request.knowledge, random.Random(request.seed))
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
        if self.telemetry is not None:
            self.telemetry.record_quota(planned=request.policy.max_backtests, consumed=len(tasks))
        self._transition(batch, BatchState.SUBMITTED)
        self._transition(batch, BatchState.RUNNING)
        for result in self.backtest_gateway.run_backtests(tasks):
            batch.record_result(result)
        for evaluation in evaluate_batch(batch, request.policy):
            batch.record_evaluation(evaluation)
        terminal_state = BatchState.COMPLETED if len(batch.results) == len(tasks) else BatchState.PARTIAL_FAILED
        self._transition(batch, terminal_state)
        templates = {
            task.task_id: next(candidate.template_id for candidate in cohort if candidate.candidate_id == task.candidate_id)
            for task in tasks
        }
        knowledge = self.knowledge_base.apply_batch(batch, templates)
        distilled_templates = self.knowledge_base.distill_batch(batch)
        mutation_proposals = propose_mutations(
            batch,
            max_proposals=request.policy.max_backtests,
            random_source=random.Random(request.seed),
        )
        self._transition(batch, BatchState.EVALUATED)
        if self.telemetry is not None:
            self.telemetry.record_backtests_completed(len(batch.results))
        return ResearchCycleSummary(
            "COMPLETED",
            round_.round_id,
            audit,
            completed_backtests=len(batch.results),
            knowledge_version=knowledge.version,
            distilled_template_count=len(distilled_templates),
            mutation_proposals=mutation_proposals,
        )
