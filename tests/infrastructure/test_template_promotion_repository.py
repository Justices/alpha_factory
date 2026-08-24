"""Durable template-promotion projection tests."""

from alpha_operator_framework.infrastructure.sqlalchemy_migrations import migrate
from alpha_operator_framework.infrastructure.sqlalchemy_repositories import SqlAlchemyTemplatePromotionRepository
from alpha_operator_framework.infrastructure.storage import StorageConfig, create_storage_engine
from alpha_operator_framework.knowledge.distillation import DistilledTemplate


def test_template_promotions_are_idempotently_persisted_with_lineage(tmp_path) -> None:
    engine = create_storage_engine(StorageConfig.from_mapping({"driver": "sqlite", "path": "research.db"}, base_path=tmp_path)); migrate(engine)
    repository = SqlAlchemyTemplatePromotionRepository(engine)
    template = DistilledTemplate("rank({a})", 2, ("round:0", "round:1"))

    repository.promote([template])
    repository.promote([template])

    assert repository.list_promoted() == [template]
