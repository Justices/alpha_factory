"""SQLite knowledge persistence tests."""

from alpha_operator_framework.infrastructure.sqlite import SqliteKnowledgeRepository
from alpha_operator_framework.knowledge.models import KnowledgeBase


def test_repository_reloads_latest_knowledge_snapshot(tmp_path) -> None:
    knowledge = KnowledgeBase(version=3, field_scores={"returns": 0.4}, operator_scores={"rank": 0.2},
                              template_scores={"rank_field": 0.1}, rejected_templates={"bad"}, field_trials={"returns": 2})
    repository = SqliteKnowledgeRepository(tmp_path / "rounds.db")

    repository.save(knowledge)

    assert repository.load() == knowledge


def test_repository_retains_immutable_version_history(tmp_path) -> None:
    repository = SqliteKnowledgeRepository(tmp_path / "knowledge.db")
    first = KnowledgeBase(version=1, field_scores={"close": 0.2})
    second = KnowledgeBase(version=2, field_scores={"open": 0.4})

    repository.save(first)
    repository.save(second)

    assert repository.load_version(1).field_scores == {"close": 0.2}
    assert repository.load_version(2).field_scores == {"open": 0.4}
