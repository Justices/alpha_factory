from __future__ import annotations

import pytest

from alpha_operator_framework.research.structure import measure_expression_structure


@pytest.mark.parametrize(("expression", "depth", "fields"), [
    ("close", 0, ("close",)),
    ("rank(close)", 1, ("close",)),
    ("ts_rank(rank(close), 20)", 2, ("close",)),
    ("ts_corr(rank(close), volume, 20)", 2, ("close", "volume")),
    ("rank(close) + rank(volume)", 2, ("close", "volume")),
    ("rank(close) + rank(close)", 2, ("close",)),
])
def test_measure_expression_structure_uses_operator_depth_and_distinct_fields(expression, depth, fields) -> None:
    structure = measure_expression_structure(expression, {"close", "volume"})

    assert structure.order_depth == depth
    assert structure.fields == fields
    assert structure.field_count == len(fields)


def test_measure_expression_structure_excludes_reserved_weight_symbol() -> None:
    structure = measure_expression_structure("group_mean(close, weight, industry)", {"close", "industry"})

    assert structure.fields == ("close", "industry")


def test_measure_expression_structure_fails_for_invalid_ast() -> None:
    with pytest.raises(ValueError, match="invalid Alpha expression"):
        measure_expression_structure("rank(", {"close"})
