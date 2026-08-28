from __future__ import annotations

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.strategies import (
    CandidateDraft,
    ConstructionContext,
    ConstructionStrategyRegistry,
)
from alpha_operator_framework.research.strategy_config import (
    ConstructionPlan,
    ConstructionStrategyConfig,
    StructuralConstraint,
)


class StaticStrategy:
    def __init__(self, kind, drafts):
        self.kind = kind
        self.drafts = drafts

    def generate(self, _context, _config):
        return self.drafts


def _config(strategy_id, kind):
    return ConstructionStrategyConfig(
        strategy_id=strategy_id,
        kind=kind,
        families=("family",),
        order_depth=StructuralConstraint(exact=1),
        field_count=StructuralConstraint(exact=1),
        source="raw_fields",
    )


def test_registry_deduplicates_cross_strategy_expression_and_preserves_provenance() -> None:
    first = CandidateDraft("rank(close)", "db", "database_template", "family", "db-template", seed=7)
    second = CandidateDraft("rank(close)", "depth", "depth_construction", "family", "depth-template", seed=7)
    registry = ConstructionStrategyRegistry((
        StaticStrategy("database_template", [first]),
        StaticStrategy("depth_construction", [second]),
    ))
    plan = ConstructionPlan((_config("db", "database_template"), _config("depth", "depth_construction")))

    outcome = registry.generate(
        plan,
        ConstructionContext((FieldSpec("close", "pv", "MATRIX"),), (), seed=7),
    )

    assert len(outcome.candidates) == 1
    assert outcome.candidates[0].origin_strategy == "db"
    assert outcome.candidates[0].family == "database_template/family/depth-1/fields-1"
    assert {item.strategy_id for item in outcome.provenances} == {"db", "depth"}
    assert len(outcome.candidates[0].provenance_ids) == 2


def test_registry_fails_closed_for_unknown_fields_and_access_limited_operators() -> None:
    drafts = [
        CandidateDraft("rank(missing)", "db", "database_template", "family"),
        CandidateDraft("vector_neut(close, close)", "db", "database_template", "family"),
    ]
    registry = ConstructionStrategyRegistry((StaticStrategy("database_template", drafts),))
    outcome = registry.generate(
        ConstructionPlan((_config("db", "database_template"),)),
        ConstructionContext((FieldSpec("close", "pv", "MATRIX"),), ()),
    )

    assert outcome.candidates == []
    assert {reason for _, reason in outcome.rejected} == {"unknown_field", "access_limited_operator"}
    assert outcome.strategy_statuses[0].status == "EXHAUSTED"


def test_registry_preserves_other_results_when_one_strategy_fails() -> None:
    class FailingStrategy:
        kind = "depth_construction"

        def generate(self, _context, _config):
            raise RuntimeError("boom")

    draft = CandidateDraft("rank(close)", "db", "database_template", "family")
    registry = ConstructionStrategyRegistry((
        StaticStrategy("database_template", [draft]),
        FailingStrategy(),
    ))
    plan = ConstructionPlan((_config("db", "database_template"), _config("depth", "depth_construction")))

    outcome = registry.generate(
        plan,
        ConstructionContext((FieldSpec("close", "pv", "MATRIX"),), ()),
    )

    assert len(outcome.candidates) == 1
    assert outcome.partial_failed is True
    assert [(status.strategy_id, status.status) for status in outcome.strategy_statuses] == [
        ("db", "GENERATED"),
        ("depth", "FAILED"),
    ]
