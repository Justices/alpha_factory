from dataclasses import replace

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.round import Candidate
from alpha_operator_framework.research.strategies import ConstructionContext, RawFirstOrderStrategy
from alpha_operator_framework.research.strategy_config import (
    ConstructionStrategyConfig, StructuralConstraint, TSWindowPolicy,
)
from alpha_operator_framework.research.exploration import balanced_cohort, refine_ts_windows
from alpha_operator_framework.research.optimization import CompletedExpression
from alpha_operator_framework.research.strategy_config import ParentGate


def candidate(field, window=5, strategy="raw", family="raw_first_order/first/depth-2/fields-1"):
    expression = f"ts_mean({field}, {window})"
    return Candidate(expression, expression, family, (field,), ("ts_mean",),
                     f"{field}:ts_mean:{window}", origin_strategy=strategy)


def test_balanced_cohort_covers_datasets_and_fields_before_duplicate_windows():
    fields = [FieldSpec("a", "a", "MATRIX"), FieldSpec("b", "b", "MATRIX")]
    pool = [candidate("a", w) for w in range(1, 100)] + [candidate("b")]
    selected = balanced_cohort(pool, (), fields, limit=2, seed=7)
    assert {c.fields[0] for c in selected} == {"a", "b"}
    assert selected == balanced_cohort(list(reversed(pool)), (), fields, limit=2, seed=7)


def test_balanced_cohort_uses_task_history_and_reserves_validation():
    fields = [FieldSpec(f, "d", "MATRIX") for f in ("a", "b")]
    validation = replace(candidate("a", 22), family="signal_validation/rank_sign", origin_strategy="validation")
    selected = balanced_cohort([candidate("a", 66), candidate("b"), validation],
                               [candidate("a")], fields, limit=2, seed=7)
    assert validation in selected
    assert candidate("b") in selected


def test_raw_ts_enabled_emits_only_coarse_probes():
    config = ConstructionStrategyConfig("raw", "raw_first_order", ("first",),
        StructuralConstraint(minimum=1, maximum=3), StructuralConstraint(exact=1))
    context = ConstructionContext((FieldSpec("x", "d", "MATRIX"),), (),
                                  ts_window_policy=TSWindowPolicy(enabled=True))
    drafts = RawFirstOrderStrategy().generate(context, config)
    means = [d.expression for d in drafts if d.template_id.startswith("x:ts_mean:")]
    assert len(means) == 3
    assert {int(d.rsplit(",", 1)[1].strip(" )")) for d in means} == {5, 66, 252}


def result(window, sharpe=1.0, fitness=0.7, operator="ts_mean", field="x"):
    expression = f"{operator}({field}, {window})"
    return CompletedExpression(expression, (field,), sharpe, fitness, False,
        expression, "raw_first_order/first/depth-2/fields-1", "raw")


def test_refinement_requires_adjacent_successful_probes_and_deduplicates():
    policy = TSWindowPolicy(enabled=True)
    assert refine_ts_windows([result(5)], policy, ParentGate()) == []
    assert refine_ts_windows([result(5), result(66, 0.1, 0.1)], policy, ParentGate()) == []
    rows = [result(5), result(66), result(252, 0.1, 0.1)]
    refinements = refine_ts_windows(rows, policy, ParentGate())
    assert [r.expression for r in refinements] == ["ts_mean(x, 22)"]
    assert len(refinements[0].parent_ids) == 2
    assert refine_ts_windows(rows + [result(22)], policy, ParentGate()) == []


def test_refinement_does_not_mix_operators_fields_or_chase_a_spike():
    policy = TSWindowPolicy(enabled=True)
    for rows in ([result(5), result(66, operator="ts_rank")],
                 [result(5), result(66, field="y")],
                 [result(5, sharpe=10), result(66)]):
        assert refine_ts_windows(rows, policy, ParentGate()) == []


def test_ts_policy_roundtrip_rejects_unbounded_or_invalid_probes():
    import pytest
    assert TSWindowPolicy.from_mapping(TSWindowPolicy(enabled=True).to_mapping()) == TSWindowPolicy(enabled=True)
    with pytest.raises(ValueError):
        TSWindowPolicy.from_mapping({"enabled": True, "probe_windows": [0, 66, 252]})
