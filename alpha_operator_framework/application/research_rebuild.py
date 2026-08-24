"""Event-only reconstruction of research projections; never calls the platform."""

from __future__ import annotations

from alpha_operator_framework.core.events import EventType
from alpha_operator_framework.experiment.lifecycle import BatchState
from alpha_operator_framework.experiment.models import BacktestResult, BacktestTask, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, ResearchPolicy, ResearchRound


class ResearchProjectionRebuilder:
    def __init__(self, event_store, research_repository, experiment_repository, knowledge_base, knowledge_repository) -> None:
        self.event_store = event_store
        self.research_repository = research_repository
        self.experiment_repository = experiment_repository
        self.knowledge_base = knowledge_base
        self.knowledge_repository = knowledge_repository

    def rebuild(self, round_id: str) -> None:
        events = self.event_store.read_stream(round_id)
        policy_event = next((event for event in events if event.event_type is EventType.POLICY_CREATED), None)
        if policy_event is None:
            raise ValueError(f"cannot rebuild {round_id}: missing PolicyCreated")
        candidates = []
        for event in events:
            if event.event_type is EventType.CANDIDATE_GENERATED:
                payload = event.payload.get("candidate")
                if not isinstance(payload, dict):
                    raise ValueError(f"cannot rebuild {round_id}: CandidateGenerated lacks candidate facts")
                candidates.append(Candidate(**payload))
        policy_data = dict(policy_event.payload["policy"])
        policy_data["prohibited_patterns"] = tuple(policy_data.get("prohibited_patterns", ()))
        self.research_repository.save_round(ResearchRound(round_id, ResearchPolicy(**policy_data), policy_event.payload["seed"], candidates))
        batch = ExperimentBatch(round_id, round_id)
        for event in events:
            if event.event_type is EventType.SIMULATION_REQUESTED:
                payload = event.payload
                task = BacktestTask(payload["task_id"], payload["candidate_id"], payload["expression"], payload["settings"], payload["idempotency_key"])
                batch.tasks[task.task_id] = task
            elif event.event_type is EventType.SIMULATION_COMPLETED:
                payload = event.payload
                batch.record_result(BacktestResult(payload["task_id"], "", payload["sharpe"], payload["fitness"], payload["turnover"], payload["margin"], payload["checks_passed"], payload.get("alpha_id")))
            elif event.event_type is EventType.VALIDATION_COMPUTED:
                payload = event.payload
                batch.record_evaluation(EvaluationRecord(payload["task_id"], payload["verdict"], payload["pareto_rank"], payload["pruned"]))
        if batch.tasks:
            batch.state = BatchState.EVALUATED if batch.evaluations else BatchState.PARTIAL_FAILED
            self.experiment_repository.save_batch(batch)
        snapshot = next((event.payload.get("knowledge") for event in reversed(events) if event.event_type is EventType.MONITORING_OBSERVED and "knowledge" in event.payload), None)
        if snapshot is None:
            raise ValueError(f"cannot rebuild {round_id}: missing knowledge snapshot event")
        self.knowledge_base = KnowledgeBase(**snapshot)
        self.knowledge_repository.save(self.knowledge_base)
