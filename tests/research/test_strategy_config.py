from __future__ import annotations

from pathlib import Path

import pytest
import yaml

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


def test_parent_gate_defaults_to_initial_promotion_thresholds() -> None:
    plan = ConstructionPlan.from_mapping({"strategies": [_strategy()]})

    assert plan.parent_gate.passes(0.61, 0.41)
    assert not plan.parent_gate.passes(0.6, 0.41)
    assert not plan.parent_gate.passes(0.61, 0.4)


def test_generation_pool_is_optional_and_independent_from_selection_quota() -> None:
    plan = ConstructionPlan.from_mapping({"strategies": [_strategy(quota_per_leaf_family=2)]})

    assert plan.strategies[0].quota_per_leaf_family == 2
    assert plan.strategies[0].generation_pool_per_leaf is None


@pytest.mark.parametrize("change,match", [
    ({"order_depth": {"exact": 2, "min": 1}}, "cannot combine"),
    ({"field_count": {"min": 2, "max": 1}}, "cannot exceed"),
    ({"quota_per_leaf_family": 9}, "between 1 and 8"),
    ({"quota_per_leaf_family": 8, "generation_pool_per_leaf": 7}, "must be at least"),
    ({"source": "qualified_candidates"}, "only supports source=raw_fields"),
    ({"stage": 0}, "stage must be positive"),
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


def test_ai_naked_signal_strategy_requires_llm_profile() -> None:
    with pytest.raises(ValueError, match="requires llm_profile"):
        ConstructionPlan.from_mapping({"strategies": [_strategy(
            id="ai", kind="ai_naked_signal", families=["ai_naked"],
        )]})


def test_ai_naked_signal_accepts_a_relative_markdown_prompt_document(tmp_path) -> None:
    prompt = tmp_path / "raw-signal.md"
    prompt.write_text("# Brief", encoding="utf-8")
    strategy = _strategy(
        id="ai", kind="ai_naked_signal", families=["ai_naked"],
        llm_profile="deepseek", prompt_document=prompt.name,
    )

    plan = ConstructionPlan.from_mapping({"strategies": [strategy]}, base_path=tmp_path)

    assert plan.strategies[0].prompt_document == prompt.resolve()


def test_ai_naked_signal_rejects_non_markdown_prompt_document(tmp_path) -> None:
    prompt = tmp_path / "raw-signal.txt"
    prompt.write_text("brief", encoding="utf-8")

    with pytest.raises(ValueError, match="Markdown"):
        ConstructionPlan.from_mapping({"strategies": [_strategy(
            id="ai", kind="ai_naked_signal", families=["ai_naked"],
            llm_profile="deepseek", prompt_document=prompt.name,
        )]}, base_path=tmp_path)


def test_construction_plan_requires_explicit_non_empty_strategy_list() -> None:
    with pytest.raises(ValueError, match="non-empty list"):
        ConstructionPlan.from_mapping({})

    with pytest.raises(ValueError, match="must be 8"):
        ConstructionPlan.from_mapping({"strategies": [_strategy()], "platform_batch_size": 4})


def test_default_configuration_exposes_separate_named_construction_modes() -> None:
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "configs" / "alpha-factory.yaml").read_text(encoding="utf-8"))

    plan = ConstructionPlan.from_mapping(
        config["research"]["construction"], base_path=root / "configs",
    )

    assert [strategy.strategy_id for strategy in plan.strategies] == [
        "database-template", "raw-first-order", "ai-naked-signals", "qualified-depth", "qualified-composition",
        "qualified-group-second-order", "signal-validation",
    ]
    assert plan.promotion.quality.min_long_short_sum == 20
    assert plan.promotion.correlation.enabled is True
    assert plan.promotion.correlation.channels == ("sharpe", "fitness", "margin")
    assert plan.promotion.validation.minimum_sharpe_ratio == 0.5
    assert plan.promotion.early_stop_signal_count == 8
    assert plan.parent_gate.passes(0.61, 0.41)
    modes = config["research"]["construction_modes"]
    assert modes["template"]["stages"] == [["database-template"]]
    assert modes["multi-stage"]["stages"] == [
        ["raw-first-order"], ["qualified-depth"],
        ["qualified-group-second-order"], ["signal-validation"],
    ]
    assert modes["ai-multi-stage"]["stages"] == [
        ["ai-naked-signals"], ["qualified-depth"],
        ["qualified-group-second-order"], ["signal-validation"],
    ]
    assert modes["multivariate"]["stages"] == [
        ["raw-first-order"], ["qualified-composition"], ["signal-validation"],
    ]
