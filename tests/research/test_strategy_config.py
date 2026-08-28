from __future__ import annotations

import pytest

from alpha_operator_framework.research.strategy_config import ConstructionPlan


def _strategy(**overrides):
    value = {
        "id": "database",
        "kind": "database_template",
        "families": ["*"],
        "order_depth": {"min": 1, "max": 3},
        "field_count": {"exact": 1},
        "quota_per_leaf_family": 8,
        "source": "raw_fields",
    }
    value.update(overrides)
    return value


def test_construction_plan_parses_exact_ranges_and_parent_gate() -> None:
    plan = ConstructionPlan.from_mapping({
        "strategies": [_strategy()],
        "parent_gate": {
            "sharpe": {"operator": "gt", "value": 1.25},
            "fitness": {"operator": "gte", "value": 0.8},
        },
        "platform_batch_size": 8,
    })

    strategy = plan.strategies[0]
    assert strategy.order_depth.contains(2)
    assert not strategy.order_depth.contains(4)
    assert strategy.field_count.contains(1)
    assert plan.parent_gate.passes(1.26, 0.8)
    assert not plan.parent_gate.passes(1.25, 0.8)


@pytest.mark.parametrize("change,match", [
    ({"order_depth": {"exact": 2, "min": 1}}, "cannot combine"),
    ({"field_count": {"min": 2, "max": 1}}, "cannot exceed"),
    ({"quota_per_leaf_family": 9}, "between 1 and 8"),
    ({"source": "qualified_candidates"}, "only supports source=raw_fields"),
    ({"kind": "unknown"}, "unsupported construction strategy"),
])
def test_construction_plan_rejects_invalid_strategy_configuration(change, match) -> None:
    with pytest.raises(ValueError, match=match):
        ConstructionPlan.from_mapping({"strategies": [_strategy(**change)]})


def test_literature_strategy_requires_existing_document_and_profile(tmp_path) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text("# Paper", encoding="utf-8")
    strategy = _strategy(
        id="paper",
        kind="literature_llm",
        families=["paper_hypothesis"],
        document=paper.name,
        llm_profile="deepseek",
    )

    plan = ConstructionPlan.from_mapping({"strategies": [strategy]}, base_path=tmp_path)

    assert plan.strategies[0].document == paper.resolve()


def test_construction_plan_requires_explicit_non_empty_strategy_list() -> None:
    with pytest.raises(ValueError, match="non-empty list"):
        ConstructionPlan.from_mapping({})

    with pytest.raises(ValueError, match="must be 8"):
        ConstructionPlan.from_mapping({"strategies": [_strategy()], "platform_batch_size": 4})
