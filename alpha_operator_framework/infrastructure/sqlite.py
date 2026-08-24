"""SQLite persistence for complete ResearchRound snapshots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from alpha_operator_framework.experiment.lifecycle import BatchState, BatchTransition
from alpha_operator_framework.experiment.models import BacktestResult, BacktestTask, EvaluationRecord, ExperimentBatch
from alpha_operator_framework.knowledge.distillation import DistilledTemplate
from alpha_operator_framework.knowledge.models import KnowledgeBase
from alpha_operator_framework.research.round import (
    Candidate,
    PruningDecision,
    ResearchPolicy,
    ResearchRound,
    SelectionDecision,
)


class SqliteResearchRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS research_round_snapshots "
                "(round_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def save_round(self, round_: ResearchRound) -> None:
        payload = json.dumps(asdict(round_), sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO research_round_snapshots(round_id, payload) VALUES (?, ?) "
                "ON CONFLICT(round_id) DO UPDATE SET payload=excluded.payload",
                (round_.round_id, payload),
            )

    def load_round(self, round_id: str) -> ResearchRound | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM research_round_snapshots WHERE round_id=?", (round_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        policy_data = dict(payload["policy"])
        policy_data["prohibited_patterns"] = tuple(policy_data["prohibited_patterns"])
        policy = ResearchPolicy(**policy_data)
        candidates = [
            Candidate(
                candidate_id=value["candidate_id"],
                expression=value["expression"],
                family=value["family"],
                fields=tuple(value["fields"]),
                operators=tuple(value["operators"]),
                template_id=value["template_id"],
                novelty_score=value["novelty_score"],
                lineage_parent_id=value["lineage_parent_id"],
            )
            for value in payload["candidates"]
        ]
        round_ = ResearchRound(
            round_id=payload["round_id"],
            policy=policy,
            seed=payload["seed"],
            candidates=candidates,
        )
        round_.selection_decisions = [
            SelectionDecision(
                candidate_id=value["candidate_id"],
                selected=value["selected"],
                score_components=value["score_components"],
                reason=value["reason"],
                policy_name=value["policy_name"],
            )
            for value in payload["selection_decisions"]
        ]
        round_.pruning_decisions = [
            PruningDecision(
                candidate_id=value["candidate_id"],
                rejected=value["rejected"],
                reason_code=value["reason_code"],
                evidence=value["evidence"],
            )
            for value in payload["pruning_decisions"]
        ]
        return round_


class SqliteExperimentRepository:
    """Persist complete experiment facts for restart-safe replay."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS experiment_batch_snapshots "
                "(batch_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def save_batch(self, batch: ExperimentBatch) -> None:
        payload = json.dumps(asdict(batch), sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO experiment_batch_snapshots(batch_id, payload) VALUES (?, ?) "
                "ON CONFLICT(batch_id) DO UPDATE SET payload=excluded.payload",
                (batch.batch_id, payload),
            )

    def load_batch(self, batch_id: str) -> ExperimentBatch | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM experiment_batch_snapshots WHERE batch_id=?", (batch_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        batch = ExperimentBatch(
            batch_id=payload["batch_id"],
            idempotency_key=payload["idempotency_key"],
            state=BatchState(payload["state"]),
        )
        batch.tasks = {
            task_id: BacktestTask(
                task_id=value["task_id"], candidate_id=value["candidate_id"],
                expression=value["expression"], settings=value["settings"],
                idempotency_key=value["idempotency_key"],
                attempts=value.get("attempts", 0), next_retry_at=value.get("next_retry_at"),
                last_error=value.get("last_error"),
            )
            for task_id, value in payload["tasks"].items()
        }
        batch.results = {
            task_id: BacktestResult(**value)
            for task_id, value in payload["results"].items()
        }
        batch.evaluations = {
            task_id: EvaluationRecord(**value)
            for task_id, value in payload["evaluations"].items()
        }
        batch.transitions = [
            BatchTransition(
                batch_id=value["batch_id"], from_state=BatchState(value["from_state"]),
                to_state=BatchState(value["to_state"]), accepted=value["accepted"], reason=value["reason"],
            )
            for value in payload["transitions"]
        ]
        return batch


class SqliteKnowledgeRepository:
    """Persist the single latest cross-round knowledge aggregate."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS knowledge_snapshot (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS knowledge_snapshot_history (version INTEGER PRIMARY KEY, payload TEXT NOT NULL)")

    def save(self, knowledge: KnowledgeBase) -> None:
        payload = json.dumps({"version": knowledge.version, "field_scores": knowledge.field_scores,
                              "operator_scores": knowledge.operator_scores, "template_scores": knowledge.template_scores,
                              "rejected_templates": sorted(knowledge.rejected_templates), "field_trials": knowledge.field_trials}, sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT INTO knowledge_snapshot(id, payload) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))
            connection.execute("INSERT OR IGNORE INTO knowledge_snapshot_history(version, payload) VALUES (?, ?)", (knowledge.version, payload))

    def load(self) -> KnowledgeBase:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT payload FROM knowledge_snapshot WHERE id=1").fetchone()
        if row is None:
            return KnowledgeBase()
        payload = json.loads(row[0])
        return KnowledgeBase(version=payload["version"], field_scores=payload["field_scores"], operator_scores=payload["operator_scores"],
                             template_scores=payload["template_scores"], rejected_templates=set(payload["rejected_templates"]), field_trials=payload["field_trials"])

    def load_version(self, version: int) -> KnowledgeBase:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT payload FROM knowledge_snapshot_history WHERE version=?", (version,)).fetchone()
        if row is None:
            raise KeyError(version)
        payload = json.loads(row[0])
        return KnowledgeBase(version=payload["version"], field_scores=payload["field_scores"], operator_scores=payload["operator_scores"],
                             template_scores=payload["template_scores"], rejected_templates=set(payload["rejected_templates"]), field_trials=payload["field_trials"])


class SqliteTemplatePromotionRepository:
    """Durable projection of reusable templates and their source-task lineage."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS template_promotions "
                "(expression_template TEXT PRIMARY KEY, support INTEGER NOT NULL, source_task_ids TEXT NOT NULL)"
            )

    def promote(self, templates: list[DistilledTemplate]) -> None:
        with sqlite3.connect(self.path) as connection:
            for template in templates:
                row = connection.execute(
                    "SELECT support, source_task_ids FROM template_promotions WHERE expression_template = ?",
                    (template.expression_template,),
                ).fetchone()
                source_ids = set(template.source_task_ids)
                support = template.support
                if row is not None:
                    support = max(support, row[0])
                    source_ids.update(json.loads(row[1]))
                connection.execute(
                    "INSERT INTO template_promotions(expression_template, support, source_task_ids) VALUES (?, ?, ?) "
                    "ON CONFLICT(expression_template) DO UPDATE SET support=excluded.support, source_task_ids=excluded.source_task_ids",
                    (template.expression_template, support, json.dumps(sorted(source_ids))),
                )

    def list_promoted(self) -> list[DistilledTemplate]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT expression_template, support, source_task_ids FROM template_promotions ORDER BY expression_template"
            ).fetchall()
        return [DistilledTemplate(row[0], row[1], tuple(json.loads(row[2]))) for row in rows]
