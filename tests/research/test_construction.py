"""Pure AST candidate construction tests."""

from __future__ import annotations

from alpha_operator_framework.domain.fields import FieldSpec
from alpha_operator_framework.generation.template_library import build_family_template_rows
from alpha_operator_framework.research.construction import (
    AstCandidateBuilder,
    ConstructionTemplate,
)


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
