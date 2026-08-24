"""SQLite knowledge persistence tests."""

from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import SqlAlchemyKnowledgeRepository
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.knowledge.models import KnowledgeBase


def test_repository_reloads_latest_knowledge_snapshot(tmp_path) -> None:
    knowledge = KnowledgeBase(version=3, field_scores={"returns": 0.4}, operator_scores={"rank": 0.2},
                              template_scores={"rank_field": 0.1}, rejected_templates={"bad"}, field_trials={"returns": 2})
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "rounds.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyKnowledgeRepository(engine)

    repository.save(knowledge)

    assert repository.load() == knowledge


def test_repository_retains_immutable_version_history(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "knowledge.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyKnowledgeRepository(engine)
    first = KnowledgeBase(version=1, field_scores={"close": 0.2})
    second = KnowledgeBase(version=2, field_scores={"open": 0.4})

    repository.save(first)
    repository.save(second)

    assert repository.load_version(1).field_scores == {"close": 0.2}
    assert repository.load_version(2).field_scores == {"open": 0.4}


def test_repository_records_queryable_knowledge_lineage(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "knowledge.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyKnowledgeRepository(engine)

    repository.save(KnowledgeBase(version=1), round_id="round-1", policy_version="policy-7", event_offset=42)

    history = repository.history_for_round("round-1")
    assert history[0]["policy_version"] == "policy-7"
    assert history[0]["event_offset"] == 42
    assert history[0]["created_at"]
