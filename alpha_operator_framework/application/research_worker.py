"""Event-led, restart-safe execution worker for submitted research batches."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from alpha_operator_framework.application.research_cycle import ResearchCycleSummary
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.experiment.evaluation import evaluate_batch
from alpha_operator_framework.experiment.lifecycle import BatchState, transition
from alpha_operator_framework.experiment.mutation import propose_mutations
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import ResearchPolicy


class ResearchBatchWorker:
    """Consumes one submitted batch; snapshots are projections, events retain its audit trail."""

    def __init__(
        self,
        event_store: Any,
        research_repository: Any,
        experiment_repository: Any,
        knowledge_base: KnowledgeBase,
        backtest_gateway: Any,
        knowledge_repository: Any | None = None,
        template_repository: Any | None = None,
        telemetry: Any | None = None,
        evidence_gateway: Any | None = None,
        submission_outbox: Any | None = None,
    ) -> None:
        self.event_store = event_store
        self.research_repository = research_repository
        self.experiment_repository = experiment_repository
        self.knowledge_base = knowledge_base
        self.backtest_gateway = backtest_gateway
        self.knowledge_repository = knowledge_repository
        self.template_repository = template_repository
        self.telemetry = telemetry
        self.evidence_gateway = evidence_gateway
        self.submission_outbox = submission_outbox

    def _event(self, event_type: EventType, round_id: str, payload: dict[str, Any]) -> None:
        self.event_store.append(Event.create(event_type, round_id, payload, actor="worker:research-batch"))

    def _policy(self, round_id: str) -> ResearchPolicy:
        for event in self.event_store.read_stream(round_id):
            if event.event_type is EventType.POLICY_CREATED:
                payload = dict(event.payload["policy"])
                payload["prohibited_patterns"] = tuple(payload.get("prohibited_patterns", ()))
                return ResearchPolicy(**payload)
        raise ValueError(f"missing PolicyCreated event for {round_id}")

    def _transition(self, batch: Any, target: BatchState) -> None:
        record = transition(batch, target)
        if not record.accepted:
            raise ValueError(f"invalid batch transition {record.from_state} -> {target}")
        self.experiment_repository.save_batch(batch)
        if self.telemetry is not None:
            self.telemetry.record_transition(batch, record)

    def _summary(self, batch: Any, status: str, knowledge_version: int = 0, templates: int = 0) -> ResearchCycleSummary:
        return ResearchCycleSummary(
            status=status,
            round_id=batch.batch_id,
            selection_audit=[],
            completed_backtests=len(batch.results),
            knowledge_version=knowledge_version,
            distilled_template_count=templates,
            mutation_proposals=[],
        )

    def process_round(self, round_id: str) -> ResearchCycleSummary:
        batch = self.experiment_repository.load_batch(round_id)
        if batch is None:
            raise ValueError(f"missing experiment batch for {round_id}")
        if batch.state is BatchState.EVALUATED:
            return self._summary(batch, "COMPLETED", self.knowledge_base.version)
        policy = self._policy(round_id)
        round_ = self.research_repository.load_round(round_id)
        if round_ is None:
            raise ValueError(f"missing research round projection for {round_id}")
        if batch.state in {BatchState.SUBMITTED, BatchState.PARTIAL_FAILED}:
            self._transition(batch, BatchState.RUNNING)
        if batch.state is not BatchState.RUNNING:
            raise ValueError(f"batch {round_id} is not runnable: {batch.state}")

        now = datetime.now(UTC)
        missing = [task for task in batch.tasks.values() if task.task_id not in batch.results]
        due = [task for task in missing if task.next_retry_at is None or datetime.fromisoformat(task.next_retry_at) <= now]
        if not due:
            return self._summary(batch, "RETRY_SCHEDULED")
        try:
            results = self.backtest_gateway.run_backtests(due)
        except (TimeoutError, ConnectionError) as error:
            attempts = max(task.attempts for task in due) + 1
            if attempts >= 3:
                batch.record_retry([task.task_id for task in due], next_retry_at=now.isoformat(), error=str(error))
                self._transition(batch, BatchState.FAILED)
                self._event(EventType.MONITORING_OBSERVED, round_id, {"alert": "retry_budget_exhausted", "error": str(error)[:1000]})
                return self._summary(batch, "FAILED")
            retry_at = now + timedelta(seconds=(30, 60, 120)[attempts - 1])
            batch.record_retry([task.task_id for task in due], next_retry_at=retry_at.isoformat(), error=str(error))
            self._transition(batch, BatchState.PARTIAL_FAILED)
            return self._summary(batch, "RETRY_SCHEDULED")
        for result in results:
            batch.record_result(result)
            task = batch.tasks[result.task_id]
            self._event(EventType.SIMULATION_COMPLETED, round_id, {
                "task_id": result.task_id, "alpha_id": result.platform_alpha_id,
                "sharpe": result.sharpe, "fitness": result.fitness, "turnover": result.turnover,
                "margin": result.margin, "checks_passed": result.checks_passed,
                "idempotency_key": task.idempotency_key,
            })
        if len(batch.results) != len(batch.tasks):
            self._transition(batch, BatchState.PARTIAL_FAILED)
            return self._summary(batch, "PARTIAL_FAILED")

        self._transition(batch, BatchState.COMPLETED)
        for evaluation in evaluate_batch(batch, policy):
            batch.record_evaluation(evaluation)
            self._event(EventType.VALIDATION_COMPUTED, round_id, {
                "task_id": evaluation.task_id, "verdict": evaluation.verdict,
                "pareto_rank": evaluation.pareto_rank, "pruned": evaluation.pruned,
            })
            if evaluation.verdict == "READY" and not evaluation.pruned:
                result = batch.results[evaluation.task_id]
                self._event(EventType.DECISION_PROPOSED, round_id, {
                    "task_id": evaluation.task_id, "alpha_id": result.platform_alpha_id,
                    "pareto_rank": evaluation.pareto_rank, "decision_state": "PENDING_EVIDENCE",
                })
                if self.evidence_gateway is not None:
                    from alpha_operator_framework.knowledge.submission import SubmissionCase

                    case = SubmissionCase.from_result(result, self.evidence_gateway.evidence_for(result))
                    approval = case.approve()
                    self._event(
                        EventType.DECISION_APPROVED if approval.is_approved else EventType.DECISION_REJECTED,
                        round_id,
                        {"task_id": evaluation.task_id, "alpha_id": result.platform_alpha_id, "reason": approval.reason},
                    )
                    if approval.is_approved and self.submission_outbox is not None:
                        self.submission_outbox.enqueue(case)
        templates_by_candidate = {candidate.candidate_id: candidate.template_id for candidate in round_.candidates}
        templates = {task.task_id: templates_by_candidate[task.candidate_id] for task in batch.tasks.values()}
        knowledge = self.knowledge_base.apply_batch(batch, templates)
        distilled = self.knowledge_base.distill_batch(batch)
        if self.knowledge_repository is not None:
            self.knowledge_repository.save(self.knowledge_base)
        if self.template_repository is not None:
            self.template_repository.promote(distilled)
        self._transition(batch, BatchState.EVALUATED)
        if self.telemetry is not None:
            self.telemetry.record_backtests_completed(len(batch.results))
        return ResearchCycleSummary(
            status="COMPLETED",
            round_id=round_id,
            selection_audit=[],
            completed_backtests=len(batch.results),
            knowledge_version=knowledge.version,
            distilled_template_count=len(distilled),
            mutation_proposals=propose_mutations(
                batch,
                max_proposals=policy.max_backtests,
                random_source=random.Random(round_.seed),
            ),
        )
