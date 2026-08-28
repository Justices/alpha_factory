"""Pure AST candidate construction tests."""

from __future__ import annotations

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.database.models import Template
from alpha_operator_framework.generation.template_library import build_family_template_rows
from alpha_operator_framework.research.construction import (
    AstCandidateBuilder,
    ConstructionTemplate,
)
from alpha_operator_framework.research.round import Candidate
from alpha_operator_framework.research.strategy_config import StructuralConstraint


def test_builder_constructs_canonical_candidates_from_configured_templates() -> None:
    templates = (
        ConstructionTemplate("rank_field", "rank({field})", "cross_sectional", ("rank",)),
        ConstructionTemplate("ts_rank_22", "ts_rank({field}, 22)", "time_series", ("ts_rank",)),
    )

    candidates = AstCandidateBuilder().build(("returns",), templates)

    assert [candidate.expression for candidate in candidates] == ["rank(returns)", "ts_rank(returns, 22)"]
    assert [candidate.template_id for candidate in candidates] == ["rank_field", "ts_rank_22"]
    assert all(candidate.fields == ("returns",) for candidate in candidates)


def test_builder_discards_invalid_or_duplicate_ast_templates() -> None:
    templates = (
        ConstructionTemplate("first", "rank({field})", "family", ("rank",)),
        ConstructionTemplate("duplicate", "rank({field})", "family", ("rank",)),
        ConstructionTemplate("invalid", "unknown_operator({field})", "family", ("unknown_operator",)),
    )

    candidates = AstCandidateBuilder().build(("returns",), templates)

    assert [candidate.template_id for candidate in candidates] == ["first"]


def test_builder_excludes_access_limited_operators_from_generated_candidates() -> None:
    templates = (
        ConstructionTemplate("allowed", "rank({field})", "family", ("rank",)),
        ConstructionTemplate("regression", "regression_neut({field}, {field})", "family", ("regression_neut",)),
        ConstructionTemplate("log", "s_log_1p({field})", "family", ("s_log_1p",)),
        ConstructionTemplate("vector", "vector_neut({field}, {field})", "family", ("vector_neut",)),
        ConstructionTemplate("delta_limit", "ts_delta_limit({field}, {field})", "family", ("ts_delta_limit",)),
        ConstructionTemplate("group_mean", "group_mean({field}, {field})", "family", ("group_mean",)),
    )

    candidates = AstCandidateBuilder().build(("returns",), templates)

    assert [candidate.expression for candidate in candidates] == ["rank(returns)"]


def test_preprocessed_builder_converts_matrix_vector_and_event_fields() -> None:
    fields = (
        FieldSpec("matrix_field", "dataset", "MATRIX"),
        FieldSpec("vector_field", "dataset", "VECTOR"),
        FieldSpec("event_field", "dataset", "EVENT"),
    )

    templates = (ConstructionTemplate("rank_field", "rank({field})", "cross_sectional", ("rank",)),)
    candidates = AstCandidateBuilder().build_preprocessed(fields, templates)

    expressions = [candidate.expression for candidate in candidates]
    assert any("ts_backfill(matrix_field, 120)" in expression for expression in expressions)
    assert any("vec_" in expression and "vector_field" in expression for expression in expressions)
    assert any("vec_avg(event_field)" in expression for expression in expressions)


def test_template_library_builder_uses_every_active_family() -> None:
    fields = (
        FieldSpec("first", "dataset", "MATRIX"),
        FieldSpec("second", "dataset", "MATRIX"),
        FieldSpec("third", "dataset", "MATRIX"),
        FieldSpec("industry", "dataset", "GROUP"),
    )

    candidates = AstCandidateBuilder().build_template_library(build_family_template_rows(), fields, sample_n=1)

    assert {candidate.family for candidate in candidates} == {"unary", "binary", "ternary", "quaternary"}
    assert all("vector_neut" not in candidate.expression for candidate in candidates)


def test_transform_uses_structural_depth_constraint_and_excludes_access_limited_operators() -> None:
    parent = Candidate("parent", "rank(close)", "base", ("close",), ("rank",), "base")
    templates = (
        Template(name="ts_rank", family="unary", expression_template="ts_rank({a}, 22)", slot_count=1),
        Template(name="zscore", family="unary", expression_template="zscore({a})", slot_count=1),
        Template(name="vector_neut", family="unary", expression_template="vector_neut({a})", slot_count=1),
        Template(name="disabled", family="unary", expression_template="rank({a})", slot_count=1, active=0),
    )

    candidates = AstCandidateBuilder().build_transform(
        parent,
        (),
        templates,
        order_depth=StructuralConstraint(exact=2),
        field_count=StructuralConstraint(exact=1),
    )

    assert {candidate.template_id for candidate in candidates} == {"ts_rank", "zscore"}
    assert {candidate.order_depth for candidate in candidates} == {2}


def test_transform_combines_distinct_fields_and_caps_each_template() -> None:
    parent = Candidate("parent", "rank(close)", "base", ("close",), ("rank",), "base")
    fields = [FieldSpec("close", "pv", "MATRIX", category="price")]
    fields.extend(FieldSpec(f"peer_{index}", "pv", "MATRIX", category="price") for index in range(250))
    fields.append(FieldSpec("volume", "pv", "MATRIX", category="volume"))
    templates = (Template(name="spread", family="binary", expression_template="{a} - {b}", slot_count=2),)

    candidates = AstCandidateBuilder().build_transform(
        parent,
        fields,
        templates,
        order_depth=StructuralConstraint(exact=2),
        field_count=StructuralConstraint(exact=2),
        seed=7,
    )

    assert 1 <= len(candidates) <= 200
    assert {candidate.family for candidate in candidates} == {"binary"}
    assert {candidate.field_count for candidate in candidates} == {2}
    assert all("close" in candidate.fields for candidate in candidates)


def test_template_library_builder_naked_and_vector_reduction_rules() -> None:
    fields = (
        FieldSpec("close", "dataset", "MATRIX", category="price"),
        FieldSpec("vector_field", "dataset", "VECTOR", category="price"),
        FieldSpec("event_field", "dataset", "EVENT", category="price"),
    )
    # 简单的单变量模板以测试生成的表达式
    templates = (
        Template(name="rank_tpl", family="unary", template_type="placeholder", expression_template="rank({a})", slot_count=1, active=1),
    )

    candidates = AstCandidateBuilder().build_template_library(templates, fields)
    expressions = [candidate.expression for candidate in candidates]

    # 验证 MATRIX 走统一缺失值预处理
    assert "rank(ts_backfill(close, 120))" in expressions

    # VECTOR / EVENT 先降维，再走统一缺失值预处理
    assert "rank(ts_backfill(vec_avg(vector_field), 120))" in expressions

    # 验证 EVENT 字段使用 vec_avg 降维
    assert "rank(ts_backfill(vec_avg(event_field), 120))" in expressions

    # 当前预处理不再叠加 winsorize
    for expr in expressions:
        assert "winsorize" not in expr
