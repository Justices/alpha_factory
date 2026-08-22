"""SQLite persistence for complete ResearchRound snapshots."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

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
