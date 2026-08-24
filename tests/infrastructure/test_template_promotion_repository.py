"""Durable template-promotion projection tests."""

from alpha_operator_framework.infrastructure.sqlite import SqliteTemplatePromotionRepository
from alpha_operator_framework.knowledge.distillation import DistilledTemplate


def test_template_promotions_are_idempotently_persisted_with_lineage(tmp_path) -> None:
    repository = SqliteTemplatePromotionRepository(tmp_path / "research.db")
    template = DistilledTemplate("rank({a})", 2, ("round:0", "round:1"))

    repository.promote([template])
    repository.promote([template])

    assert repository.list_promoted() == [template]
