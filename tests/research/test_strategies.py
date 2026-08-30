from __future__ import annotations

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.research.strategies import (
    AiNakedSignalStrategy,
    CandidateDraft,
    ConstructionContext,
    ConstructionStrategyRegistry,
)
from alpha_operator_framework.research.strategy_config import (
    ConstructionPlan,
    ConstructionStrategyConfig,
    StructuralConstraint,
)
from alpha_operator_framework.research.round import Candidate


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


def test_group_second_order_uses_group_fields_in_context_when_cache_scope_is_unset() -> None:
    parent = Candidate("parent", "rank(returns)", "base", ("returns",), ("rank",), "base")
    config = ConstructionStrategyConfig(
        strategy_id="qualified-group",
        kind="group_second_order",
        families=("group_second_order",),
        order_depth=StructuralConstraint(exact=2),
        field_count=StructuralConstraint(exact=2),
        source="qualified_candidates",
    )

    outcome = ConstructionStrategyRegistry().generate(
        ConstructionPlan((config,)),
        ConstructionContext(
            (FieldSpec("returns", "pv", "MATRIX"), FieldSpec("industry", "pv", "GROUP")),
            (), parents=(parent,), seed=7,
        ),
    )

    assert {candidate.expression for candidate in outcome.candidates} == {
        "group_neutralize(rank(returns), densify(industry))",
        "group_rank(rank(returns), densify(industry))",
        "group_zscore(rank(returns), densify(industry))",
    }
    assert all(candidate.lineage_parent_id == "parent" for candidate in outcome.candidates)


def test_group_second_order_prefers_exact_scope_cached_groups(monkeypatch) -> None:
    from alpha_operator_framework.research import field_loader

    parent = Candidate("parent", "rank(returns)", "base", ("returns",), ("rank",), "base")
    config = ConstructionStrategyConfig(
        strategy_id="qualified-group",
        kind="group_second_order",
        families=("group_second_order",),
        order_depth=StructuralConstraint(exact=2),
        field_count=StructuralConstraint(exact=2),
        source="qualified_candidates",
    )
    monkeypatch.setattr(
        field_loader,
        "load_or_fetch_group_fields",
        lambda region, universe, delay: [FieldSpec("sector", "pv", "GROUP")],
    )

    outcome = ConstructionStrategyRegistry().generate(
        ConstructionPlan((config,)),
        ConstructionContext(
            (FieldSpec("returns", "pv", "MATRIX"), FieldSpec("industry", "pv", "GROUP")),
            (), parents=(parent,), region="GBR", universe="TOP700", delay=1,
        ),
    )

    assert all("densify(sector)" in candidate.expression for candidate in outcome.candidates)


def test_raw_first_order_expands_fields_without_database_templates() -> None:
    config = ConstructionStrategyConfig(
        strategy_id="raw-first-order",
        kind="raw_first_order",
        families=("first_order",),
        order_depth=StructuralConstraint(minimum=1, maximum=3),
        field_count=StructuralConstraint(exact=1),
        source="raw_fields",
    )

    outcome = ConstructionStrategyRegistry().generate(
        ConstructionPlan((config,)),
        ConstructionContext((FieldSpec("returns", "pv", "MATRIX"),), (), seed=7),
    )

    expressions = {candidate.expression for candidate in outcome.candidates}
    assert "rank(ts_backfill(returns, 120))" in expressions
    assert "ts_rank(ts_backfill(returns, 120), 504)" in expressions
    assert all("500" not in expression and "240" not in expression for expression in expressions)


def test_signal_validation_generates_terminal_rank_and_sign_children() -> None:
    parent = Candidate("parent", "ts_delta(returns, 22)", "base", ("returns",), ("ts_delta",), "base")
    config = ConstructionStrategyConfig(
        strategy_id="signal-validation",
        kind="signal_validation",
        families=("rank_sign",),
        order_depth=StructuralConstraint(minimum=1, maximum=3),
        field_count=StructuralConstraint(exact=1),
        source="qualified_candidates",
    )

    outcome = ConstructionStrategyRegistry().generate(
        ConstructionPlan((config,)),
        ConstructionContext((FieldSpec("returns", "pv", "MATRIX"),), (), parents=(parent,)),
    )

    assert {candidate.expression for candidate in outcome.candidates} == {
        "rank(ts_delta(returns, 22))",
        "sign(ts_delta(returns, 22))",
    }
    assert all(candidate.lineage_parent_id == "parent" for candidate in outcome.candidates)


def test_ai_naked_signal_grounds_vector_fields_before_ast_acceptance() -> None:
    class FakeLlm:
        def chat(self, **_kwargs):
            return """[
              {
                "title": "Attention reversal",
                "expression": "rank(news_vector)",
                "rationale": "Attention overreaction creates temporary mispricing; behavioral reversal signal."
              }
            ]"""

    config = ConstructionStrategyConfig(
        strategy_id="ai-naked",
        kind="ai_naked_signal",
        families=("ai_naked",),
        order_depth=StructuralConstraint(minimum=1, maximum=4),
        field_count=StructuralConstraint(exact=1),
        source="raw_fields",
        llm_profile="deepseek",
    )
    registry = ConstructionStrategyRegistry((AiNakedSignalStrategy(FakeLlm()),))

    outcome = registry.generate(
        ConstructionPlan((config,)),
        ConstructionContext((
            FieldSpec("news_vector", "news", "VECTOR", description="News attention vector"),
        ), (), seed=7),
    )

    assert len(outcome.candidates) == 1
    assert "vec_" in outcome.candidates[0].expression
    assert "ts_backfill" in outcome.candidates[0].expression
    assert '"rationale":"Attention overreaction' in outcome.provenances[0].hypothesis_id


def test_ai_naked_signal_uses_type_aware_scalarization_and_cycles_vector_ops() -> None:
    class FakeLlm:
        def chat(self, **_kwargs):
            return """[
              {"title":"Vector 1","expression":"rank(news_vector)","rationale":"Economic mechanism one."},
              {"title":"Vector 2","expression":"rank(news_vector)","rationale":"Economic mechanism two."},
              {"title":"Vector 3","expression":"rank(news_vector)","rationale":"Economic mechanism three."},
              {"title":"Matrix","expression":"rank(matrix_field)","rationale":"Economic mechanism four."},
              {"title":"Event","expression":"rank(event_field)","rationale":"Economic mechanism five."}
            ]"""

    config = ConstructionStrategyConfig(
        strategy_id="ai-naked",
        kind="ai_naked_signal",
        families=("ai_naked",),
        order_depth=StructuralConstraint(minimum=1, maximum=4),
        field_count=StructuralConstraint(exact=1),
        source="raw_fields",
        llm_profile="deepseek",
    )
    outcome = ConstructionStrategyRegistry((AiNakedSignalStrategy(FakeLlm()),)).generate(
        ConstructionPlan((config,)),
        ConstructionContext((
            FieldSpec("news_vector", "news", "VECTOR"),
            FieldSpec("matrix_field", "fundamental", "MATRIX"),
            FieldSpec("event_field", "events", "EVENT"),
            FieldSpec("sector", "groups", "GROUP"),
        ), (), seed=7),
    )

    expressions = {candidate.expression for candidate in outcome.candidates}
    vector_expressions = {item for item in expressions if "news_vector" in item}
    vector_reducers = {
        operator
        for operator in ("vec_avg", "vec_sum", "vec_min", "vec_max", "vec_stddev", "vec_range", "vec_count")
        if any(f"{operator}(news_vector)" in item for item in vector_expressions)
    }
    assert len(vector_expressions) == 3
    assert len(vector_reducers) == 3
    assert any("ts_backfill(matrix_field, 120)" in item for item in expressions)
    assert all("vec_" not in item for item in expressions if "matrix_field" in item)
    assert any("vec_avg(event_field)" in item for item in expressions)
    assert all("sector" not in item for item in expressions)
