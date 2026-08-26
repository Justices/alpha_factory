"""SQLAlchemy implementations of the research runtime persistence ports."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert, select, update

from alpha_operator_framework.experiment.lifecycle import BatchState, BatchTransition
from alpha_operator_framework.experiment.models import BacktestResult, BacktestTask, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, PruningDecision, ResearchPolicy, ResearchRound, SelectionDecision

from .sqlalchemy_migrations import (
    event_log,
    knowledge_snapshot,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _round(payload: str) -> ResearchRound:
    value = json.loads(payload)
    policy_data = dict(value["policy"])
    policy_data["prohibited_patterns"] = tuple(policy_data["prohibited_patterns"])
    policy_data["retry_backoff_seconds"] = tuple(policy_data.get("retry_backoff_seconds", (30.0, 60.0, 120.0)))
    result = ResearchRound(
        round_id=value["round_id"], policy=ResearchPolicy(**policy_data), seed=value["seed"],
        candidates=[Candidate(
            candidate_id=item["candidate_id"], expression=item["expression"], family=item["family"],
            fields=tuple(item["fields"]), operators=tuple(item["operators"]), template_id=item["template_id"],
            novelty_score=item["novelty_score"], lineage_parent_id=item["lineage_parent_id"],
        ) for item in value["candidates"]],
    )
    result.selection_decisions = [SelectionDecision(**item) for item in value["selection_decisions"]]
    result.pruning_decisions = [PruningDecision(**item) for item in value["pruning_decisions"]]
    return result


def _batch(payload: str) -> ExperimentBatch:
    value = json.loads(payload)
    result = ExperimentBatch(
        batch_id=value["batch_id"], idempotency_key=value["idempotency_key"],
        storage_batch_id=value.get("storage_batch_id"), state=BatchState(value["state"]),
    )
    result.tasks = {task_id: BacktestTask(
        task_id=item["task_id"], candidate_id=item["candidate_id"], expression=item["expression"],
        settings=item["settings"], idempotency_key=item["idempotency_key"], attempts=item.get("attempts", 0),
        next_retry_at=item.get("next_retry_at"), last_error=item.get("last_error"),
    ) for task_id, item in value["tasks"].items()}
    result.results = {task_id: BacktestResult(**item) for task_id, item in value["results"].items()}
    result.evaluations = {task_id: EvaluationRecord(**item) for task_id, item in value["evaluations"].items()}
    result.transitions = [BatchTransition(
        batch_id=item["batch_id"], from_state=BatchState(item["from_state"]), to_state=BatchState(item["to_state"]),
        accepted=item["accepted"], reason=item["reason"],
    ) for item in value["transitions"]]
    return result


def _knowledge(payload: str) -> KnowledgeBase:
    value = json.loads(payload)
    return KnowledgeBase(
        version=value["version"], field_scores=value["field_scores"], operator_scores=value["operator_scores"],
        template_scores=value["template_scores"], rejected_templates=set(value["rejected_templates"]),
        field_trials=value["field_trials"],
    )


class _SnapshotRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._items: dict[str, str] = {}

    def _save(self, identifier: str, payload: str, *, status: str, error: str | None = None) -> None:
        self._items[identifier] = payload

    def _load(self, identifier: str) -> str | None:
        return self._items.get(identifier)


class SqlAlchemyResearchRepository(_SnapshotRepository):

    def save_round(self, round_: ResearchRound) -> None:
        self._save(round_.round_id, _json(asdict(round_)), status="PLANNED")

    def load_round(self, round_id: str) -> ResearchRound | None:
        payload = self._load(round_id)
        return _round(payload) if payload is not None else None


class SqlAlchemyExperimentRepository(_SnapshotRepository):

    def save_batch(self, batch: ExperimentBatch) -> None:
        errors = sorted({task.last_error for task in batch.tasks.values() if task.last_error})
        self._save(batch.batch_id, _json(asdict(batch)), status=batch.state.value, error="; ".join(errors) or None)

    def load_batch(self, batch_id: str) -> ExperimentBatch | None:
        payload = self._load(batch_id)
        return _batch(payload) if payload is not None else None

    def list_due_batches(self) -> list[ExperimentBatch]:
        """Return non-terminal batches with at least one task ready to run."""
        now = datetime.now(UTC)
        batches = [_batch(payload) for payload in self._items.values()]
        return [
            batch for batch in batches
            if batch.state in {BatchState.SUBMITTED, BatchState.PARTIAL_FAILED}
            and any(
                task.task_id not in batch.results
                and (task.next_retry_at is None or datetime.fromisoformat(task.next_retry_at) <= now)
                for task in batch.tasks.values()
            )
        ]


class SqlAlchemyKnowledgeRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(self, knowledge: KnowledgeBase, *, round_id: str | None = None, policy_version: str | None = None, event_offset: int | None = None) -> None:
        payload = _json({"version": knowledge.version, "field_scores": knowledge.field_scores,
                         "operator_scores": knowledge.operator_scores, "template_scores": knowledge.template_scores,
                         "rejected_templates": sorted(knowledge.rejected_templates), "field_trials": knowledge.field_trials})
        with self.engine.begin() as connection:
            if connection.execute(update(knowledge_snapshot).where(knowledge_snapshot.c.id == 1).values(payload=payload)).rowcount == 0:
                connection.execute(insert(knowledge_snapshot).values(id=1, payload=payload))

    def load(self) -> KnowledgeBase:
        with self.engine.connect() as connection:
            payload = connection.execute(select(knowledge_snapshot.c.payload).where(knowledge_snapshot.c.id == 1)).scalar_one_or_none()
        return _knowledge(payload) if payload is not None else KnowledgeBase()

class SqlAlchemyEventRepository:
    """Minimal append-only repository required by :class:`EventStore`."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append_event(self, **values: Any) -> int:
        values["payload"] = values.pop("payload_json")
        values["metadata"] = values.pop("metadata_json")
        with self.engine.begin() as connection:
            result = connection.execute(insert(event_log).values(**values))
            return int(result.inserted_primary_key[0])

    def append_events_batch(self, rows: list[tuple[Any, ...]]) -> list[int]:
        keys = ("event_id", "stream_id", "event_type", "schema_version", "payload", "payload_ref", "occurred_at", "actor", "metadata")
        return [self.append_event(**dict(zip(keys, row, strict=True))) for row in rows]

    def _read(self, statement: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def read_events_by_stream(self, stream_id: str, from_offset: int) -> list[dict[str, Any]]:
        return self._read(select(event_log).where(event_log.c.stream_id == stream_id, event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset))

    def read_all_events(self, from_offset: int, limit: int | None) -> list[dict[str, Any]]:
        statement = select(event_log).where(event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset)
        return self._read(statement.limit(limit) if limit is not None else statement)

    def read_events_by_type(self, event_type: str, from_offset: int) -> list[dict[str, Any]]:
        return self._read(select(event_log).where(event_log.c.event_type == event_type, event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset))
