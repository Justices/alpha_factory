"""SQLAlchemy implementations of the research runtime persistence ports."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import Engine, delete, insert, select, update

from alpha_operator_framework.experiment.lifecycle import BatchState, BatchTransition
from alpha_operator_framework.experiment.models import BacktestResult, BacktestTask, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.distillation import DistilledTemplate
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import Candidate, PruningDecision, ResearchPolicy, ResearchRound, SelectionDecision

from .sqlalchemy_migrations import (
    event_log,
    experiment_batch_snapshots,
    knowledge_snapshot,
    knowledge_snapshot_history,
    research_round_snapshots,
    template_promotions,
)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _round(payload: str) -> ResearchRound:
    value = json.loads(payload)
    policy_data = dict(value["policy"])
    policy_data["prohibited_patterns"] = tuple(policy_data["prohibited_patterns"])
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
    result = ExperimentBatch(batch_id=value["batch_id"], idempotency_key=value["idempotency_key"], state=BatchState(value["state"]))
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
    table: Any
    identifier: Any

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _save(self, identifier: str, payload: str) -> None:
        with self.engine.begin() as connection:
            statement = update(self.table).where(self.identifier == identifier).values(payload=payload)
            if connection.execute(statement).rowcount == 0:
                connection.execute(insert(self.table).values({self.identifier.name: identifier, "payload": payload}))

    def _load(self, identifier: str) -> str | None:
        with self.engine.connect() as connection:
            return connection.execute(select(self.table.c.payload).where(self.identifier == identifier)).scalar_one_or_none()


class SqlAlchemyResearchRepository(_SnapshotRepository):
    table = research_round_snapshots
    identifier = research_round_snapshots.c.round_id

    def save_round(self, round_: ResearchRound) -> None:
        self._save(round_.round_id, _json(asdict(round_)))

    def load_round(self, round_id: str) -> ResearchRound | None:
        payload = self._load(round_id)
        return _round(payload) if payload is not None else None


class SqlAlchemyExperimentRepository(_SnapshotRepository):
    table = experiment_batch_snapshots
    identifier = experiment_batch_snapshots.c.batch_id

    def save_batch(self, batch: ExperimentBatch) -> None:
        self._save(batch.batch_id, _json(asdict(batch)))

    def load_batch(self, batch_id: str) -> ExperimentBatch | None:
        payload = self._load(batch_id)
        return _batch(payload) if payload is not None else None


class SqlAlchemyKnowledgeRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(self, knowledge: KnowledgeBase) -> None:
        payload = _json({"version": knowledge.version, "field_scores": knowledge.field_scores,
                         "operator_scores": knowledge.operator_scores, "template_scores": knowledge.template_scores,
                         "rejected_templates": sorted(knowledge.rejected_templates), "field_trials": knowledge.field_trials})
        with self.engine.begin() as connection:
            if connection.execute(update(knowledge_snapshot).where(knowledge_snapshot.c.id == 1).values(payload=payload)).rowcount == 0:
                connection.execute(insert(knowledge_snapshot).values(id=1, payload=payload))
            if connection.execute(select(knowledge_snapshot_history.c.version).where(knowledge_snapshot_history.c.version == knowledge.version)).scalar_one_or_none() is None:
                connection.execute(insert(knowledge_snapshot_history).values(version=knowledge.version, payload=payload))

    def load(self) -> KnowledgeBase:
        with self.engine.connect() as connection:
            payload = connection.execute(select(knowledge_snapshot.c.payload).where(knowledge_snapshot.c.id == 1)).scalar_one_or_none()
        return _knowledge(payload) if payload is not None else KnowledgeBase()

    def load_version(self, version: int) -> KnowledgeBase:
        with self.engine.connect() as connection:
            payload = connection.execute(select(knowledge_snapshot_history.c.payload).where(knowledge_snapshot_history.c.version == version)).scalar_one_or_none()
        if payload is None:
            raise KeyError(version)
        return _knowledge(payload)


class SqlAlchemyTemplatePromotionRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def promote(self, templates: list[DistilledTemplate]) -> None:
        with self.engine.begin() as connection:
            for template in templates:
                current = connection.execute(select(template_promotions.c.support, template_promotions.c.source_task_ids).where(
                    template_promotions.c.expression_template == template.expression_template)).one_or_none()
                support, source_ids = template.support, set(template.source_task_ids)
                if current is not None:
                    support = max(support, current.support)
                    source_ids.update(json.loads(current.source_task_ids))
                    connection.execute(update(template_promotions).where(
                        template_promotions.c.expression_template == template.expression_template).values(
                        support=support, source_task_ids=_json(sorted(source_ids))))
                else:
                    connection.execute(insert(template_promotions).values(
                        expression_template=template.expression_template, support=support, source_task_ids=_json(sorted(source_ids))))

    def list_promoted(self) -> list[DistilledTemplate]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(template_promotions).order_by(template_promotions.c.expression_template)).mappings().all()
        return [DistilledTemplate(row["expression_template"], row["support"], tuple(json.loads(row["source_task_ids"]))) for row in rows]


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
