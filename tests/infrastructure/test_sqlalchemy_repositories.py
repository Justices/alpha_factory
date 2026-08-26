"""Behaviour tests for the driver-neutral research persistence adapters."""

from alpha_operator_framework.core.event_store import EventStore
from alpha_operator_framework.core.events import Event, EventType
from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import SqlAlchemyEventRepository, SqlAlchemyKnowledgeRepository
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.knowledge.models import KnowledgeBase


def test_sqlalchemy_repositories_persist_knowledge_and_events(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path))
    migrate(engine)
    knowledge = SqlAlchemyKnowledgeRepository(engine)
    knowledge.save(KnowledgeBase(version=3, field_scores={"close": 0.7}))
    store = EventStore(persistent=True, repository=SqlAlchemyEventRepository(engine))
    store.append(Event.create(EventType.POLICY_CREATED, "round-1", {"round_id": "round-1"}))

    assert knowledge.load().field_scores == {"close": 0.7}
    assert store.read_stream("round-1")[0].payload == {"round_id": "round-1"}
