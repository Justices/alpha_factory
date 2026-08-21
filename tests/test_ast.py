"""Unit tests for Alpha AST engine (parsing, canonicalization, validation, pruning)."""

import pytest

from alpha_operator_framework.domain.ast import (
    ExpressionNode,
    VariableNode,
    LiteralNode,
    UnaryOpNode,
    BinaryOpNode,
    FunctionCallNode,
    TernaryNode,
    parse_expression,
    canonicalize_expression,
    to_canonical_string,
    get_canonical_sha,
    validate_expression,
    extract_ast_fields,
)
from alpha_operator_framework.domain.pruning import ast_canonical_prune
from alpha_operator_framework.domain.families import Task


def test_parse_basic_expression():
    node = parse_expression("rank(close) / rank(volume)")
    assert isinstance(node, BinaryOpNode)
    assert node.op == "/"
    assert isinstance(node.left, FunctionCallNode)
    assert node.left.name == "rank"
    assert isinstance(node.left.args[0], VariableNode)
    assert node.left.args[0].name == "close"


def test_parse_ternary_expression():
    node = parse_expression("(close > open ? close - open : 0)")
    assert isinstance(node, TernaryNode)
    assert isinstance(node.condition, BinaryOpNode)
    assert node.condition.op == ">"
    assert isinstance(node.true_expr, BinaryOpNode)
    assert node.true_expr.op == "-"
    assert isinstance(node.false_expr, LiteralNode)
    assert node.false_expr.value == 0


def test_commutative_reordering():
    # a + b vs b + a
    expr1 = "volume + close"
    expr2 = "close + volume"
    can1 = to_canonical_string(expr1)
    can2 = to_canonical_string(expr2)
    assert can1 == "close + volume"
    assert can1 == can2
    assert get_canonical_sha(expr1) == get_canonical_sha(expr2)

    # Multi-term associative reordering
    expr3 = "c + a + b"
    can3 = to_canonical_string(expr3)
    assert can3 == "a + b + c"


def test_redundant_operator_elimination():
    # rank(rank(x)) -> rank(x)
    assert to_canonical_string("rank(rank(close))") == "rank(close)"
    assert to_canonical_string("zscore(zscore(close))") == "zscore(close)"

    # reverse(reverse(x)) -> x
    assert to_canonical_string("reverse(reverse(close))") == "close"

    # ts_rank(ts_rank(x, 10), 10) -> ts_rank(x, 10)
    assert to_canonical_string("ts_rank(ts_rank(close, 10), 10)") == "ts_rank(close, 10)"

    # ts_delay combining
    assert to_canonical_string("ts_delay(ts_delay(close, 5), 10)") == "ts_delay(close, 15)"

    # double negative
    assert to_canonical_string("-(-close)") == "close"


def test_algebraic_constant_folding():
    assert to_canonical_string("close + 0") == "close"
    assert to_canonical_string("0 + close") == "close"
    assert to_canonical_string("close * 1") == "close"
    assert to_canonical_string("close / 1") == "close"
    assert to_canonical_string("close * 0") == "0"
    assert to_canonical_string("2 + 3") == "5"
    assert to_canonical_string("10 * 5") == "50"


def test_ast_validation():
    # Valid expression
    res = validate_expression("group_neutralize(ts_rank(close, 22), industry)")
    assert res.is_valid
    assert "close" in res.fields_used
    assert "industry" in res.fields_used
    assert "ts_rank" in res.operators_used
    assert "group_neutralize" in res.operators_used

    # Illegal vector nesting
    bad_vec = "vec_avg(vec_sum(volume_vector))"
    res_vec = validate_expression(bad_vec)
    assert not res_vec.is_valid
    assert any("Illegal vector nesting" in err for err in res_vec.errors)

    # Invalid time-series window (string or non-positive)
    bad_ts = "ts_rank(close, -5)"
    res_ts = validate_expression(bad_ts)
    assert not res_ts.is_valid
    assert any("window must be positive integer" in err for err in res_ts.errors)

    # Divide by literal zero
    bad_div = "close / 0"
    res_div = validate_expression(bad_div)
    assert not res_div.is_valid
    assert any("Division by literal zero" in err for err in res_div.errors)


def test_field_extraction():
    fields = extract_ast_fields("ts_delta(close, 10) / (high - low + volume)")
    assert sorted(fields) == ["close", "high", "low", "volume"]


def test_ast_canonical_prune():
    tasks = [
        Task(expression="close + volume", template_index=0, family="unary", fields_per_alpha=1),
        Task(expression="volume + close", template_index=0, family="unary", fields_per_alpha=1), # duplicate by commutativity
        Task(expression="rank(rank(close))", template_index=1, family="unary", fields_per_alpha=1), # redundant nest
        Task(expression="rank(close)", template_index=1, family="unary", fields_per_alpha=1), # duplicate after canonicalization
        Task(expression="open / close", template_index=2, family="binary", fields_per_alpha=2),
    ]

    kept, pruned = ast_canonical_prune(tasks)
    assert len(kept) == 3  # "close + volume", "rank(close)", "open / close"
    assert len(pruned) == 2
    # Check that rank(rank(close)) was simplified in place
    exprs_kept = [t.expression for t in kept]
    assert "close + volume" in exprs_kept
    assert "rank(close)" in exprs_kept
    assert "open / close" in exprs_kept
