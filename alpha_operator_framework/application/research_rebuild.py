"""Event-only reconstruction of research projections; never calls the platform."""

from __future__ import annotations

import inspect

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
        explicit_state: BatchState | None = None
        for event in events:
            if event.event_type is EventType.SIMULATION_REQUESTED:
                payload = event.payload
                task = BacktestTask(payload["task_id"], payload["candidate_id"], payload["expression"], payload["settings"], payload["idempotency_key"])
                batch.tasks[task.task_id] = task
            elif event.event_type is EventType.MONITORING_OBSERVED and "retry" in event.payload:
                retry = event.payload["retry"]
                for task_facts in retry.get("tasks", []):
                    task = batch.tasks[task_facts["task_id"]]
                    batch.tasks[task.task_id] = BacktestTask(
                        task.task_id, task.candidate_id, task.expression, task.settings, task.idempotency_key,
                        attempts=task_facts["attempts"], next_retry_at=task_facts["next_retry_at"],
                        last_error=task_facts["last_error"],
                    )
                explicit_state = BatchState(retry["state"])
            elif event.event_type is EventType.SIMULATION_COMPLETED:
                payload = event.payload
                batch.record_result(BacktestResult(payload["task_id"], "", payload["sharpe"], payload["fitness"], payload["turnover"], payload["margin"], payload["checks_passed"], payload.get("alpha_id")))
            elif event.event_type is EventType.VALIDATION_COMPUTED:
                payload = event.payload
                batch.record_evaluation(EvaluationRecord(payload["task_id"], payload["verdict"], payload["pareto_rank"], payload["pruned"]))
        if batch.tasks:
            has_all_results = len(batch.results) == len(batch.tasks)
            has_all_evaluations = has_all_results and len(batch.evaluations) == len(batch.tasks)
            batch.state = (
                BatchState.EVALUATED if has_all_evaluations
                else BatchState.COMPLETED if has_all_results
                else explicit_state if explicit_state is not None
                else BatchState.PARTIAL_FAILED
            )
            self.experiment_repository.save_batch(batch)
        snapshot_event = next((event for event in reversed(events) if event.event_type is EventType.MONITORING_OBSERVED and "knowledge" in event.payload), None)
        if snapshot_event is None:
            raise ValueError(f"cannot rebuild {round_id}: missing knowledge snapshot event")
        self.knowledge_base = KnowledgeBase(**snapshot_event.payload["knowledge"])
        event_offset = self._event_offset(snapshot_event)
        metadata = {"round_id": round_id, "policy_version": policy_data.get("policy_version"), "event_offset": event_offset}
        save = self.knowledge_repository.save
        try:
            supports_metadata = True
            inspect.signature(save).bind(self.knowledge_base, **metadata)
        except TypeError:
            supports_metadata = False
        except ValueError:
            supports_metadata = False
        if supports_metadata:
            save(self.knowledge_base, **metadata)
        else:
            save(self.knowledge_base)

    def _event_offset(self, source_event) -> int | None:
        """Read the persisted global offset when the event store exposes it."""
        repository = getattr(self.event_store, "_repository", None)
        if repository is not None and hasattr(repository, "read_all_events"):
            for row in repository.read_all_events(0, None):
                if row["event_id"] == source_event.event_id:
                    return row.get("global_offset")
        return next(
            (index for index, event in enumerate(self.event_store.read_all(), start=1) if event.event_id == source_event.event_id),
            None,
        )
