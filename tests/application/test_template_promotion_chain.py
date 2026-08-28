"""End-to-end feedback from distilled evidence to database-template candidates."""

from alpha_operator_framework.database import AlphaDatabase
from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.strategies import (
    ConstructionContext,
    ConstructionStrategyRegistry,
)
from alpha_operator_framework.research.strategy_config import (
    ConstructionPlan,
    ConstructionStrategyConfig,
    StructuralConstraint,
)


def _database_plan() -> ConstructionPlan:
    return ConstructionPlan((ConstructionStrategyConfig(
        strategy_id="promoted-db",
        kind="database_template",
        families=("evolved_distillation",),
        order_depth=StructuralConstraint(exact=1),
        field_count=StructuralConstraint(exact=1),
        source="raw_fields",
    ),))


def test_promoted_template_evidence_survives_reopen_and_is_consumed(tmp_path) -> None:
    database_path = tmp_path / "promotion-chain.db"
    database = AlphaDatabase(database_path)
    database.save_abstracted_template(
        "rank({a})",
        support_count=2,
        source_task_ids=("round-1:0", "round-1:1"),
        example_expression="rank(close)",
    )
    database.save_abstracted_template(
        "rank({a})",
        support_count=2,
        source_task_ids=("round-1:1", "round-2:0"),
        example_expression="rank(volume)",
    )
    database.close()

    reopened = AlphaDatabase(database_path)
    templates = reopened.list_templates(families=("evolved_distillation",))

    assert len(templates) == 1
    assert templates[0].source["support"] == 3
    assert templates[0].source["source_task_ids"] == [
        "round-1:0", "round-1:1", "round-2:0",
    ]
    assert templates[0].example_expression == "rank(close)"

    outcome = ConstructionStrategyRegistry().generate(
        _database_plan(),
        ConstructionContext(
            fields=(FieldSpec("close", "pv", "MATRIX"),),
            templates=tuple(templates),
            seed=7,
        ),
    )

    assert [candidate.expression for candidate in outcome.candidates] == ["rank(close)"]
    assert outcome.candidates[0].origin_strategy == "promoted-db"
    assert outcome.strategy_statuses[0].status == "GENERATED"
    reopened.close()


def test_legacy_support_is_retained_as_a_lower_bound(tmp_path) -> None:
    database = AlphaDatabase(tmp_path / "legacy-promotion.db")
    database.save_abstracted_template("rank({a})", support_count=5)
    database.save_abstracted_template(
        "rank({a})",
        support_count=1,
        source_task_ids=("new-round:0",),
    )

    template = database.list_templates(families=("evolved_distillation",))[0]

    assert template.source["support"] == 5
    assert template.source["source_task_ids"] == ["new-round:0"]
    database.close()
