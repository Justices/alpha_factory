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


def test_order2_uses_every_compatible_active_template_and_excludes_vector_neut() -> None:
    parent = Candidate("parent", "rank(close)", "base", ("close",), ("rank",), "base")
    templates = (
        Template(name="ts_rank", family="unary", expression_template="ts_rank({a}, 22)", slot_count=1),
        Template(name="zscore", family="unary", expression_template="zscore({a})", slot_count=1),
        Template(name="vector_neut", family="unary", expression_template="vector_neut({a})", slot_count=1),
        Template(name="disabled", family="unary", expression_template="rank({a})", slot_count=1, active=0),
    )

    candidates = AstCandidateBuilder().build_order2(parent, templates)

    assert {candidate.template_id for candidate in candidates} == {"ts_rank", "zscore"}
    assert {candidate.family for candidate in candidates} == {"optimization_order2"}


def test_dimension2_uses_different_fields_from_the_parent_category_and_caps_each_template() -> None:
    parent = Candidate("parent", "rank(close)", "base", ("close",), ("rank",), "base")
    fields = [FieldSpec("close", "pv", "MATRIX", category="price")]
    fields.extend(FieldSpec(f"peer_{index}", "pv", "MATRIX", category="price") for index in range(250))
    fields.append(FieldSpec("volume", "pv", "MATRIX", category="volume"))
    templates = (Template(name="spread", family="binary", expression_template="{a} - {b}", slot_count=2),)

    candidates = AstCandidateBuilder().build_dimension2(parent, fields, templates, seed=7)

    assert len(candidates) == 200
    assert {candidate.family for candidate in candidates} == {"optimization_dimension2"}
    assert all("close" in candidate.fields for candidate in candidates)
    assert all("volume" not in candidate.fields for candidate in candidates)


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

    # 验证 MATRIX 使用裸字段 (不含 winsorize 或 ts_backfill)
    assert "rank(close)" in expressions

    # 验证 VECTOR 字段确定性展开为四种 vec_* 降维形式 (且不含 winsorize)
    assert "rank(vec_avg(vector_field))" in expressions
    assert "rank(vec_sum(vector_field))" in expressions
    assert "rank(vec_range(vector_field))" in expressions
    assert "rank(vec_stddev(vector_field))" in expressions

    # 验证 EVENT 字段使用 vec_avg 降维
    assert "rank(vec_avg(event_field))" in expressions

    # 确保生成结果绝对没有任何最外层或内层的 winsorize 或 ts_backfill 包装
    for expr in expressions:
        assert "winsorize" not in expr
        assert "ts_backfill" not in expr
