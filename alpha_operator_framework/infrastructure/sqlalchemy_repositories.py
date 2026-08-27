"""SQLAlchemy implementations of the research runtime persistence ports."""

from __future__ import annotations

import json
import logging
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
    experiment_batch_snapshot,
    knowledge_snapshot,
    research_round_snapshot,
)

logger = logging.getLogger(__name__)


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
    """快照仓储基类，封装基础的基于 SQLAlchemy 的二进制 JSON 快照读写逻辑。"""
    table: Any
    identifier_column: str

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _save(self, identifier: str, payload: str, *, status: str, error: str | None = None) -> None:
        values = {self.identifier_column: identifier, "payload": payload, "status": status, "error": error}
        logger.info("保存快照数据: 表=%s, 标识符=%s, 状态=%s", self.table.name, identifier, status)
        with self.engine.begin() as connection:
            if connection.execute(
                update(self.table).where(self.table.c[self.identifier_column] == identifier).values(**values)
            ).rowcount == 0:
                connection.execute(insert(self.table).values(**values))

    def _load(self, identifier: str) -> str | None:
        logger.info("加载快照数据: 表=%s, 标识符=%s", self.table.name, identifier)
        with self.engine.connect() as connection:
            return connection.execute(
                select(self.table.c.payload).where(self.table.c[self.identifier_column] == identifier)
            ).scalar_one_or_none()


class SqlAlchemyResearchRepository(_SnapshotRepository):
    """SQLAlchemy 编写的研究回合 (ResearchRound) 快照仓储实现。"""
    table = research_round_snapshot
    identifier_column = "round_id"

    def save_round(self, round_: ResearchRound) -> None:
        """保存研究回合到快照库中。"""
        logger.info("正在将研究回合 %s 持久化至快照库...", round_.round_id)
        self._save(round_.round_id, _json(asdict(round_)), status="PLANNED")

    def load_round(self, round_id: str) -> ResearchRound | None:
        """根据 Round ID 从快照库加载对应回合。"""
        logger.info("正在从快照库反序列化加载研究回合 %s...", round_id)
        payload = self._load(round_id)
        return _round(payload) if payload is not None else None


class SqlAlchemyExperimentRepository(_SnapshotRepository):
    """SQLAlchemy 编写的实验批次 (ExperimentBatch) 快照仓储实现。"""
    table = experiment_batch_snapshot
    identifier_column = "batch_id"

    def save_batch(self, batch: ExperimentBatch) -> None:
        """保存实验批次快照。"""
        errors = sorted({task.last_error for task in batch.tasks.values() if task.last_error})
        logger.info("正在保存实验批次 %s (状态: %s)...", batch.batch_id, batch.state.value)
        self._save(batch.batch_id, _json(asdict(batch)), status=batch.state.value, error="; ".join(errors) or None)

    def load_batch(self, batch_id: str) -> ExperimentBatch | None:
        """根据 Batch ID 反序列化加载实验批次。"""
        logger.info("正在加载实验批次 %s...", batch_id)
        payload = self._load(batch_id)
        return _batch(payload) if payload is not None else None

    def list_due_batches(self) -> list[ExperimentBatch]:
        """获取当前准备好运行的未决/重试批次列表。"""
        logger.info("正在扫描过期或准备运行的批次队列...")
        now = datetime.now(UTC)
        with self.engine.connect() as connection:
            batches = [_batch(payload) for payload in connection.execute(select(self.table.c.payload)).scalars()]
        
        due_batches = [
            batch for batch in batches
            if batch.state in {BatchState.SUBMITTED, BatchState.PARTIAL_FAILED}
            and any(
                task.task_id not in batch.results
                and (task.next_retry_at is None or datetime.fromisoformat(task.next_retry_at) <= now)
                for task in batch.tasks.values()
            )
        ]
        logger.info("批次队列扫描完毕。共发现 %d 个满足运行条件的批次", len(due_batches))
        return due_batches


class SqlAlchemyKnowledgeRepository:
    """SQLAlchemy 编写的知识库 (KnowledgeBase) 快照仓储实现。"""
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save(self, knowledge: KnowledgeBase, *, round_id: str | None = None, policy_version: str | None = None, event_offset: int | None = None) -> None:
        """保存最新的全局进化知识库快照。"""
        logger.info("正在保存最新的全局知识库快照 (version=%s)...", knowledge.version)
        payload = _json({"version": knowledge.version, "field_scores": knowledge.field_scores,
                         "operator_scores": knowledge.operator_scores, "template_scores": knowledge.template_scores,
                         "rejected_templates": sorted(knowledge.rejected_templates), "field_trials": knowledge.field_trials})
        with self.engine.begin() as connection:
            if connection.execute(update(knowledge_snapshot).where(knowledge_snapshot.c.id == 1).values(payload=payload)).rowcount == 0:
                connection.execute(insert(knowledge_snapshot).values(id=1, payload=payload))

    def load(self) -> KnowledgeBase:
        """加载最新的全局知识库。"""
        logger.info("正在加载最新的全局知识库...")
        with self.engine.connect() as connection:
            payload = connection.execute(select(knowledge_snapshot.c.payload).where(knowledge_snapshot.c.id == 1)).scalar_one_or_none()
        result = _knowledge(payload) if payload is not None else KnowledgeBase()
        logger.info("全局知识库反序列化加载成功，当前知识库版本: %s", result.version)
        return result


class SqlAlchemyEventRepository:
    """事件存储引擎 EventStore 专用的轻量只追加 SQLAlchemy 仓储实现。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append_event(self, **values: Any) -> int:
        """追加单条事件条目并返回其主键偏移值。"""
        values["payload"] = values.pop("payload_json")
        values["metadata"] = values.pop("metadata_json")
        logger.info("正在追加单条事件: event_type=%s, stream_id=%s", values.get("event_type"), values.get("stream_id"))
        with self.engine.begin() as connection:
            result = connection.execute(insert(event_log).values(**values))
            return int(result.inserted_primary_key[0])

    def append_events_batch(self, rows: list[tuple[Any, ...]]) -> list[int]:
        """批量追加事件。"""
        logger.info("正在批量追加 %d 个事件...", len(rows))
        keys = ("event_id", "stream_id", "event_type", "schema_version", "payload", "payload_ref", "occurred_at", "actor", "metadata")
        return [self.append_event(**dict(zip(keys, row, strict=True))) for row in rows]

    def _read(self, statement: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def read_events_by_stream(self, stream_id: str, from_offset: int) -> list[dict[str, Any]]:
        """从指定 Stream 中读取其全球偏移量大于指定偏移的事件。"""
        logger.info("读取事件流: stream_id=%s, 起始偏移=%d", stream_id, from_offset)
        return self._read(select(event_log).where(event_log.c.stream_id == stream_id, event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset))

    def read_all_events(self, from_offset: int, limit: int | None) -> list[dict[str, Any]]:
        """按全局唯一偏移重放所有事件流。"""
        logger.info("全局重放所有事件流: 起始偏移=%d, 限制数量=%s", from_offset, limit)
        statement = select(event_log).where(event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset)
        return self._read(statement.limit(limit) if limit is not None else statement)

    def read_events_by_type(self, event_type: str, from_offset: int) -> list[dict[str, Any]]:
        """按事件类型加载特定偏移后的事件流。"""
        logger.info("按类型重放事件流: event_type=%s, 起始偏移=%d", event_type, from_offset)
        return self._read(select(event_log).where(event_log.c.event_type == event_type, event_log.c.global_offset > from_offset).order_by(event_log.c.global_offset))
