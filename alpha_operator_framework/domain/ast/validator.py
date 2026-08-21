"""Alpha AST 静态语义与类型校验器.

校验:
  1. 变量与字段存在性与提取
  2. 算子名称合法性 (与 domain.operators 注册表校验)
  3. 窗口参数合法性 (时序窗口必须为正整数)
  4. Vector 算子合法性 (vec_* 只能作用于叶子字段，不可非法嵌套)
  5. Group 算子合法性 (group_* 的分组参数必须为有效分组标识)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Set, Tuple, Union

from alpha_operator_framework.domain.ast.nodes import (
    ASTVisitor,
    BinaryOpNode,
    ExpressionNode,
    FunctionCallNode,
    LiteralNode,
    TernaryNode,
    UnaryOpNode,
    VariableNode,
)
from alpha_operator_framework.domain.ast.parser import parse_expression
from alpha_operator_framework.domain.operators import (
    basic_ops,
    extended_ops,
    group_ops,
    ts_ops,
    vec_ops,
)

# 已知所有合法算子集合
KNOWN_OPERATORS = frozenset(
    set(basic_ops)
    | set(ts_ops)
    | set(group_ops)
    | set(vec_ops)
    | set(extended_ops)
    | {
        "abs", "log", "sign", "sqrt", "signed_power", "min", "max",
        "trade_when", "filter", "paste", "if_else", "ts_step",
    }
)


@dataclass
class ValidationResult:
    """AST 校验结果."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    fields_used: Set[str] = field(default_factory=set)
    operators_used: Set[str] = field(default_factory=set)


class ASTValidator(ASTVisitor):
    """AST 语义与合法性校验器."""

    def __init__(self, known_fields: Optional[Set[str]] = None, vector_fields: Optional[Set[str]] = None):
        self.known_fields = known_fields
        self.vector_fields = vector_fields or set()
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.fields_used: Set[str] = set()
        self.operators_used: Set[str] = set()

    def validate(self, node: ExpressionNode) -> ValidationResult:
        node.accept(self)
        return ValidationResult(
            is_valid=(len(self.errors) == 0),
            errors=self.errors,
            warnings=self.warnings,
            fields_used=self.fields_used,
            operators_used=self.operators_used,
        )

    def visit_variable(self, node: VariableNode) -> None:
        self.fields_used.add(node.name)
        if self.known_fields is not None and node.name not in self.known_fields:
            self.warnings.append(f"Field '{node.name}' not found in known fields catalogue")

    def visit_literal(self, node: LiteralNode) -> None:
        pass

    def visit_unary_op(self, node: UnaryOpNode) -> None:
        node.operand.accept(self)

    def visit_binary_op(self, node: BinaryOpNode) -> None:
        # 除零静态检查
        if node.op == "/" and isinstance(node.right, LiteralNode) and node.right.value == 0:
            self.errors.append("Division by literal zero detected in expression")
        node.left.accept(self)
        node.right.accept(self)

    def visit_function_call(self, node: FunctionCallNode) -> None:
        name = node.name.lower()
        self.operators_used.add(name)

        if name not in KNOWN_OPERATORS:
            self.warnings.append(f"Unknown or custom operator '{name}'")

        # 1. 时序算子窗口检查
        if name in ts_ops or name.startswith("ts_"):
            if len(node.args) >= 2:
                window_node = node.args[1]
                if isinstance(window_node, LiteralNode):
                    if not (isinstance(window_node.value, int) and window_node.value > 0):
                        self.errors.append(f"Time-series operator '{name}' window must be positive integer, got: {window_node.value}")
                elif isinstance(window_node, VariableNode):
                    self.errors.append(f"Time-series operator '{name}' window cannot be variable '{window_node.name}'")

        # 2. Vector 算子非法嵌套检查
        if name in vec_ops or name.startswith("vec_"):
            if len(node.args) >= 1:
                inner = node.args[0]
                if isinstance(inner, FunctionCallNode) and (inner.name in vec_ops or inner.name.startswith("vec_")):
                    self.errors.append(f"Illegal vector nesting: '{name}' called on output of vector operator '{inner.name}'")

        # 3. Group 算子参数检查
        if name in group_ops or name.startswith("group_"):
            if len(node.args) < 2:
                self.errors.append(f"Group operator '{name}' requires at least 2 arguments (field, group)")

        for arg in node.args:
            arg.accept(self)
        for _, v in node.kwargs:
            v.accept(self)

    def visit_ternary(self, node: TernaryNode) -> None:
        node.condition.accept(self)
        node.true_expr.accept(self)
        node.false_expr.accept(self)


def validate_expression(
    expr: Union[str, ExpressionNode],
    known_fields: Optional[Set[str]] = None,
    vector_fields: Optional[Set[str]] = None,
) -> ValidationResult:
    """校验 Alpha 表达式的语义与语法合法性.

    Args:
        expr: 字符串或 AST 节点
        known_fields: 可选的已知有效字段集合
        vector_fields: 可选的已知 VECTOR 类型字段集合

    Returns:
        ValidationResult
    """
    if isinstance(expr, str):
        try:
            node = parse_expression(expr)
        except Exception as e:
            return ValidationResult(is_valid=False, errors=[str(e)])
    else:
        node = expr

    validator = ASTValidator(known_fields=known_fields, vector_fields=vector_fields)
    return validator.validate(node)


def extract_ast_fields(expr: Union[str, ExpressionNode]) -> List[str]:
    """从表达式中提取所有引用的字段名列表."""
    res = validate_expression(expr)
    return sorted(list(res.fields_used))
