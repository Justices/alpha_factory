from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....database.config import DEFAULT_SQLITE_PATH, get_database_path
from ...domain.field_research.models import FieldProfile, FieldSnapshot, FieldUniverse
from ...domain.field_research.ports import FieldProfileRepositoryPort
from ...domain.candidate_exploration.models import Candidate, PrePruneDecision, ResearchPolicy, SelectionDecision, SelectionRound
from ...domain.candidate_exploration.ports import CandidateRepositoryPort
from ...domain.experiment_governance.models import (
    BacktestTask,
    EvaluationRecord,
    ExperimentBatch,
    NormalizedBacktestResult,
    PostPruneDecision,
)
from ...domain.experiment_governance.ports import ExperimentRepositoryPort
from ...domain.knowledge_and_submission.models import (
    KnowledgeBase,
    PruneRuleEvidence,
    SignalDistillationEvidence,
)
from ...domain.knowledge_and_submission.ports import KnowledgeRepositoryPort


class SqliteDddRepository(
    FieldProfileRepositoryPort,
    CandidateRepositoryPort,
    ExperimentRepositoryPort,
    KnowledgeRepositoryPort,
):
    """Unified SQLite repository for DDD aggregate roots and decision events."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_database_path()
        self._init_ddd_tables()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_ddd_tables(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ddd_field_universes (
                    region TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    snapshots_json TEXT NOT NULL,
                    profiles_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (region, universe)
                );

                CREATE TABLE IF NOT EXISTS ddd_selection_rounds (
                    round_id TEXT PRIMARY KEY,
                    region TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    candidate_pool_json TEXT NOT NULL,
                    pre_prune_decisions_json TEXT NOT NULL,
                    selection_decisions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ddd_experiment_batches (
                    batch_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tasks_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    post_prune_json TEXT NOT NULL,
                    evaluations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ddd_knowledge_base (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    templates_json TEXT NOT NULL,
                    prune_rules_json TEXT NOT NULL,
                    field_signals_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    # 1. Field Universe
    def load_universe(self, region: str, universe: str) -> Optional[FieldUniverse]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM ddd_field_universes WHERE region=? AND universe=?",
                (region, universe)
            )
            row = cur.fetchone()
            if not row:
                return None
            fu = FieldUniverse(region=region, universe=universe, version=row["version"])
            snaps = json.loads(row["snapshots_json"])
            profs = json.loads(row["profiles_json"])
            for s in snaps.values():
                fu.snapshots[s["field_id"]] = FieldSnapshot(**s)
            for p in profs.values():
                fu.profiles[p["field_id"]] = FieldProfile(**p)
            return fu

    def save_universe(self, universe: FieldUniverse) -> None:
        snaps = {k: v.__dict__ for k, v in universe.snapshots.items()}
        profs = {k: v.__dict__ for k, v in universe.profiles.items()}
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO ddd_field_universes (region, universe, version, snapshots_json, profiles_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(region, universe) DO UPDATE SET
                     version=excluded.version,
                     snapshots_json=excluded.snapshots_json,
                     profiles_json=excluded.profiles_json,
                     updated_at=excluded.updated_at
                """,
                (universe.region, universe.universe, universe.version, json.dumps(snaps), json.dumps(profs))
            )

    # 2. Selection Round
    def save_round(self, selection_round: SelectionRound) -> None:
        cands = {k: v.__dict__ for k, v in selection_round.candidate_pool.items()}
        pre_prunes = {k: v.__dict__ for k, v in selection_round.pre_prune_decisions.items()}
        sels = {k: v.__dict__ for k, v in selection_round.selection_decisions.items()}
        policy_dict = {
            "version": selection_round.policy.version,
            "region": selection_round.policy.region,
            "universe": selection_round.policy.universe,
            "selection_algorithm": selection_round.policy.selection_algorithm,
        }
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO ddd_selection_rounds (round_id, region, universe, policy_json, seed, status, candidate_pool_json, pre_prune_decisions_json, selection_decisions_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(round_id) DO UPDATE SET
                     status=excluded.status,
                     pre_prune_decisions_json=excluded.pre_prune_decisions_json,
                     selection_decisions_json=excluded.selection_decisions_json
                """,
                (
                    selection_round.round_id,
                    selection_round.policy.region,
                    selection_round.policy.universe,
                    json.dumps(policy_dict),
                    selection_round.seed,
                    selection_round.status,
                    json.dumps(cands),
                    json.dumps(pre_prunes),
                    json.dumps(sels),
                )
            )

    def load_round(self, round_id: str) -> Optional[SelectionRound]:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM ddd_selection_rounds WHERE round_id=?", (round_id,))
            row = cur.fetchone()
            if not row:
                return None
            p_dict = json.loads(row["policy_json"])
            policy = ResearchPolicy(
                region=p_dict["region"],
                universe=p_dict["universe"],
                selection_algorithm=p_dict["selection_algorithm"],
            )
            sr = SelectionRound(round_id=round_id, policy=policy, seed=row["seed"], status=row["status"])
            for k, v in json.loads(row["candidate_pool_json"]).items():
                sr.candidate_pool[k] = Candidate(**v)
            for k, v in json.loads(row["pre_prune_decisions_json"]).items():
                sr.pre_prune_decisions[k] = PrePruneDecision(**v)
            for k, v in json.loads(row["selection_decisions_json"]).items():
                sr.selection_decisions[k] = SelectionDecision(**v)
            return sr

    # 3. Experiment Batch
    def save_batch(self, batch: ExperimentBatch) -> None:
        tasks = {k: v.__dict__ for k, v in batch.tasks.items()}
        results = {k: v.__dict__ for k, v in batch.results.items()}
        prunes = {k: v.__dict__ for k, v in batch.post_prune_decisions.items()}
        evals = {k: v.__dict__ for k, v in batch.evaluations.items()}

        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO ddd_experiment_batches (batch_id, idempotency_key, status, tasks_json, results_json, post_prune_json, evaluations_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(batch_id) DO UPDATE SET
                     status=excluded.status,
                     results_json=excluded.results_json,
                     post_prune_json=excluded.post_prune_json,
                     evaluations_json=excluded.evaluations_json
                """,
                (batch.batch_id, batch.idempotency_key, batch.status, json.dumps(tasks), json.dumps(results), json.dumps(prunes), json.dumps(evals))
            )

    def load_batch(self, batch_id: str) -> Optional[ExperimentBatch]:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM ddd_experiment_batches WHERE batch_id=?", (batch_id,))
            row = cur.fetchone()
            if not row:
                return None
            batch = ExperimentBatch(batch_id=batch_id, idempotency_key=row["idempotency_key"], status=row["status"])
            for k, v in json.loads(row["tasks_json"]).items():
                batch.tasks[k] = BacktestTask(**v)
            for k, v in json.loads(row["results_json"]).items():
                batch.results[k] = NormalizedBacktestResult(**v)
            for k, v in json.loads(row["post_prune_json"]).items():
                batch.post_prune_decisions[k] = PostPruneDecision(**v)
            for k, v in json.loads(row["evaluations_json"]).items():
                batch.evaluations[k] = EvaluationRecord(**v)
            return batch

    # 4. Knowledge Base
    def load_knowledge(self) -> KnowledgeBase:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM ddd_knowledge_base WHERE id=1")
            row = cur.fetchone()
            if not row:
                return KnowledgeBase()
            kb = KnowledgeBase(version=row["version"])
            for k, v in json.loads(row["templates_json"]).items():
                kb.templates[k] = SignalDistillationEvidence(**v)
            for k, v in json.loads(row["prune_rules_json"]).items():
                kb.prune_rules[k] = PruneRuleEvidence(**v)
            kb.field_signals = json.loads(row["field_signals_json"])
            return kb

    def save_knowledge(self, knowledge_base: KnowledgeBase) -> None:
        templates = {k: v.__dict__ for k, v in knowledge_base.templates.items()}
        rules = {k: v.__dict__ for k, v in knowledge_base.prune_rules.items()}
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO ddd_knowledge_base (id, version, templates_json, prune_rules_json, field_signals_json, updated_at)
                   VALUES (1, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(id) DO UPDATE SET
                     version=excluded.version,
                     templates_json=excluded.templates_json,
                     prune_rules_json=excluded.prune_rules_json,
                     field_signals_json=excluded.field_signals_json,
                     updated_at=excluded.updated_at
                """,
                (knowledge_base.version, json.dumps(templates), json.dumps(rules), json.dumps(knowledge_base.field_signals))
            )
