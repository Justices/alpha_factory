"""Deterministic structural measurements for validated Alpha expressions."""

from __future__ import annotations

from dataclasses import dataclass

from alpha_operator_framework.domain.ast.nodes import (
    BinaryOpNode,
    ExpressionNode,
    FunctionCallNode,
    LiteralNode,
    TernaryNode,
    UnaryOpNode,
    VariableNode,
)
from alpha_operator_framework.domain.ast.parser import parse_expression
from alpha_operator_framework.domain.ast.validator import validate_expression


NON_DATA_VARIABLES = frozenset({"weight"})


@dataclass(frozen=True)
class ExpressionStructure:
    order_depth: int
    fields: tuple[str, ...]

    @property
    def field_count(self) -> int:
        return len(self.fields)


def operator_depth(node: ExpressionNode) -> int:
    if isinstance(node, (LiteralNode, VariableNode)):
        return 0
    if isinstance(node, UnaryOpNode):
        return 1 + operator_depth(node.operand)
    if isinstance(node, BinaryOpNode):
        return 1 + max(operator_depth(node.left), operator_depth(node.right))
    if isinstance(node, FunctionCallNode):
        children = [*node.args, *(value for _, value in node.kwargs)]
        return 1 + max((operator_depth(child) for child in children), default=0)
    if isinstance(node, TernaryNode):
        return 1 + max(
            operator_depth(node.condition),
            operator_depth(node.true_expr),
            operator_depth(node.false_expr),
        )
    raise TypeError(f"unsupported Alpha AST node: {type(node).__name__}")


def measure_expression_structure(
    expression: str,
    known_fields: set[str] | None = None,
) -> ExpressionStructure:
    validation_fields = None if known_fields is None else set(known_fields) | set(NON_DATA_VARIABLES)
    validation = validate_expression(expression, known_fields=validation_fields)
    if not validation.is_valid:
        raise ValueError("invalid Alpha expression: " + "; ".join(validation.errors))
    node = parse_expression(expression)
    return ExpressionStructure(
        order_depth=operator_depth(node),
        fields=tuple(sorted(set(validation.fields_used) - set(NON_DATA_VARIABLES))),
    )


def leaf_family(
    strategy_kind: str,
    template_family: str,
    structure: ExpressionStructure,
) -> str:
    return (
        f"{strategy_kind}/{template_family}/"
        f"depth-{structure.order_depth}/fields-{structure.field_count}"
    )


__all__ = [
    "ExpressionStructure",
    "NON_DATA_VARIABLES",
    "leaf_family",
    "measure_expression_structure",
    "operator_depth",
]
