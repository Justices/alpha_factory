"""SQLite replay tests for complete research-round snapshots."""

from __future__ import annotations

from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import SqlAlchemyResearchRepository
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.research.pruning import AstPrePruner
from alpha_operator_framework.research.round import Candidate, ResearchPolicy, ResearchRound
from alpha_operator_framework.research.selection import WeightedStratifiedSelector
from alpha_operator_framework.research.round import KnowledgeSnapshot
import random


def test_repository_reloads_complete_research_round_snapshot(tmp_path) -> None:
    round_ = ResearchRound(
        "round-1",
        ResearchPolicy("GBR", "TOP700", 1, field_weight=2.0),
        7,
        [Candidate("c", "rank(close)", "family", ("close",), ("rank",), "template")],
    )
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "rounds.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyResearchRepository(engine)

    repository.save_round(round_)

    assert repository.load_round("round-1") == round_


def test_repository_reloads_research_decision_audit(tmp_path) -> None:
    round_ = ResearchRound(
        "round-audit", ResearchPolicy("GBR", "TOP700", 1), 7,
        [Candidate("c", "rank(close)", "family", ("close",), ("rank",), "template")],
    )
    round_.pruning_decisions = AstPrePruner().evaluate(round_.candidates, round_.policy)
    round_.select(WeightedStratifiedSelector(), KnowledgeSnapshot(version=2), random.Random(7))
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "rounds.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyResearchRepository(engine)

    repository.save_round(round_)

    assert repository.load_round("round-audit") == round_
