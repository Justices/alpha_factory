"""Pure AST candidate construction tests."""

from __future__ import annotations

from alpha_operator_framework.research.construction import AstCandidateBuilder, ConstructionTemplate


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
