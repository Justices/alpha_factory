"""Thin application orchestration for a research-round planning cycle."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.models import ExperimentBatch, MutationProposal
from alpha_operator_framework.knowledge.models import KnowledgeBase
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
        event_store: Any | None = None,
        evidence_gateway: Any | None = None,
        submission_outbox: Any | None = None,
        alpha_database: Any | None = None,
    ) -> None:
        self.research_repository = research_repository
        self.backtest_gateway = backtest_gateway
        self.knowledge_base = knowledge_base or KnowledgeBase()
        self.experiment_repository = experiment_repository
        self.telemetry = telemetry
        self.event_store = event_store
        self.evidence_gateway = evidence_gateway
        self.submission_outbox = submission_outbox
        self.alpha_database = alpha_database

    def _event(self, event_type: Any, stream_id: str, payload: dict[str, Any]) -> None:
        if self.event_store is not None:
            from alpha_operator_framework.core.events import Event
            self.event_store.append(Event.create(event_type, stream_id, payload, actor="application:research-cycle"))

    def _save_batch(self, batch: ExperimentBatch) -> None:
        if self.experiment_repository is not None:
            self.experiment_repository.save_batch(batch)

    def _transition(self, batch: ExperimentBatch, target: BatchState) -> None:
        event = transition(batch, target)
        if self.telemetry is not None:
            self.telemetry.record_transition(batch, event)
        self._save_batch(batch)

    def execute(self, request: ResearchCycleRequest) -> ResearchCycleSummary:
        if request.execute_platform and (self.event_store is None or self.experiment_repository is None):
            raise ValueError("live research requires an event store and experiment repository")
        round_ = ResearchRound(request.round_id, request.policy, request.seed, list(request.candidates))
        generated_candidates = list(round_.candidates)
        backtest_settings = {
            "region": request.policy.region, "universe": request.policy.universe,
            "delay": request.policy.delay, "decay": request.policy.decay,
            "neutralization": request.policy.neutralization, "truncation": request.policy.truncation,
        }
        if self.alpha_database is not None:
            for candidate in generated_candidates:
                self.alpha_database.insert_expression(
                    candidate.expression, backtest_settings, expression_origin="research_cycle",
                    fields=list(candidate.fields), status="generated",
                )
            self.alpha_database.catalog_research_candidates(round_.round_id, generated_candidates, backtest_settings)
        if self.event_store is not None:
            from alpha_operator_framework.core.events import EventType
            self._event(EventType.POLICY_CREATED, round_.round_id, {"policy": asdict(request.policy), "seed": request.seed})
            self._event(EventType.FIELD_SNAPSHOT_CAPTURED, round_.round_id, {"fields": sorted({field for candidate in round_.candidates for field in candidate.fields}), "knowledge_version": request.knowledge.version})
            for candidate in round_.candidates:
                self._event(EventType.CANDIDATE_GENERATED, round_.round_id, {"candidate": asdict(candidate)})
        decisions = round_.select(build_selector(request.policy), request.knowledge, random.Random(request.seed))
        if self.alpha_database is not None:
            self.alpha_database.record_round_selection(round_.round_id, decisions)
        if self.event_store is not None:
            from alpha_operator_framework.core.events import EventType
            for decision in decisions:
                self._event(EventType.CANDIDATE_SCORED, round_.round_id, {"candidate_id": decision.candidate_id, "selected": decision.selected, "score_components": dict(decision.score_components)})
            self._event(EventType.BATCH_ALLOCATED, round_.round_id, {"selected_count": sum(decision.selected for decision in decisions), "max_backtests": request.policy.max_backtests})
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
        batch = self.experiment_repository.load_batch(round_.round_id) if self.experiment_repository is not None else None
        is_new_batch = batch is None
        if batch is not None:
            tasks = list(batch.tasks.values())
        else:
            batch = ExperimentBatch(batch_id=round_.round_id, idempotency_key=round_.round_id)
            tasks = batch.create_tasks(cohort, request.policy)
            if self.alpha_database is not None and tasks:
                batch.storage_batch_id = self.alpha_database.create_simulation_batch(
                    [{"task_id": task.task_id, "candidate_id": task.candidate_id, "expression": task.expression} for task in tasks],
                    backtest_settings, simulation_type="RESEARCH", round_id=round_.round_id,
                )
            if self.telemetry is not None:
                self.telemetry.record_quota(planned=request.policy.max_backtests, consumed=len(tasks))
            self._transition(batch, BatchState.SUBMITTED)
        if self.event_store is not None and is_new_batch:
            from alpha_operator_framework.core.events import EventType
            for task in tasks:
                self._event(EventType.SIMULATION_REQUESTED, round_.round_id, {"task_id": task.task_id, "candidate_id": task.candidate_id, "expression": task.expression, "settings": dict(task.settings), "idempotency_key": task.idempotency_key})
        return ResearchCycleSummary("SUBMITTED", round_.round_id, audit)
