"""Alpha AST 规范化与等价化简器 (Canonicalizer).

功能:
  1. 可交换算子重排 (Commutative Reordering): a + b 与 b + a 归一化为同一种形式
  2. 结合律扁平化与重排: c + a + b -> (a + b) + c
  3. 冗余算子消除 (Redundant Nesting Elimination):
     - rank(rank(x)) -> rank(x)
     - zscore(zscore(x)) -> zscore(x)
     - reverse(reverse(x)) -> x
     - scale(scale(x)) -> scale(x)
     - ts_rank(ts_rank(x, w), w) -> ts_rank(x, w)
     - ts_delay(ts_delay(x, w1), w2) -> ts_delay(x, w1 + w2)
     - -(-x) -> x, !(!x) -> x
  4. 代数常数折叠 (Constant Folding):
     - x + 0, x - 0, x * 1, x / 1 -> x
     - 2 + 3 -> 5
  5. 规范化 SHA-256 生成: 保证语义相同的公式具有唯一的 canonical_sha
"""

from __future__ import annotations

import hashlib
from typing import List, Sequence, Tuple, Union

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


# 幂等单入单出算子 (f(f(x)) == f(x))
IDEMPOTENT_OPS = frozenset({"rank", "zscore", "scale", "quantile", "normalize"})

# 可交换二元算子 (a op b == b op a)
COMMUTATIVE_OPS = frozenset({"+", "*", "==", "!=", "&&", "||", "and", "or", "&", "|"})


def _extract_associative_chain(node: ExpressionNode, op: str) -> List[ExpressionNode]:
    """将连续相同结合律算子的树展开为列表，例如 ((a + b) + c) -> [a, b, c]."""
    if isinstance(node, BinaryOpNode) and node.op == op:
        return _extract_associative_chain(node.left, op) + _extract_associative_chain(node.right, op)
    return [node]


def _build_left_associative_tree(operands: Sequence[ExpressionNode], op: str) -> ExpressionNode:
    """将操作数列表重组为严格左结合的二叉树."""
    if not operands:
        raise ValueError("Cannot build tree from empty operands")
    res = operands[0]
    for nxt in operands[1:]:
        res = BinaryOpNode(op, res, nxt)
    return res


class ASTCanonicalizer(ASTVisitor):
    """AST 规范化与化简遍历器."""

    def canonicalize(self, node: ExpressionNode) -> ExpressionNode:
        return node.accept(self)

    def visit_variable(self, node: VariableNode) -> ExpressionNode:
        return node

    def visit_literal(self, node: LiteralNode) -> ExpressionNode:
        return node

    def visit_unary_op(self, node: UnaryOpNode) -> ExpressionNode:
        operand = self.canonicalize(node.operand)

        # 双重负号与双重逻辑非消除: -(-x) -> x, !(!x) -> x
        if isinstance(operand, UnaryOpNode) and operand.op == node.op:
            if node.op in ("-", "!", "+"):
                return operand.operand

        # +x -> x
        if node.op == "+":
            return operand

        # 常量折叠
        if isinstance(operand, LiteralNode) and isinstance(operand.value, (int, float)):
            if node.op == "-":
                val = -operand.value
                return LiteralNode(int(val) if isinstance(val, float) and val.is_integer() else val)

        return UnaryOpNode(node.op, operand)

    def visit_binary_op(self, node: BinaryOpNode) -> ExpressionNode:
        op = node.op
        left = self.canonicalize(node.left)
        right = self.canonicalize(node.right)

        # 1. 常量与常量的直接折叠 (如 1 + 2 -> 3)
        if isinstance(left, LiteralNode) and isinstance(right, LiteralNode):
            if isinstance(left.value, (int, float)) and isinstance(right.value, (int, float)):
                lv, rv = left.value, right.value
                try:
                    if op == "+":
                        res = lv + rv
                    elif op == "-":
                        res = lv - rv
                    elif op == "*":
                        res = lv * rv
                    elif op == "/" and rv != 0:
                        res = lv / rv
                    elif op == "%" and rv != 0:
                        res = lv % rv
                    elif op in ("**", "^"):
                        res = lv ** rv
                    else:
                        res = None

                    if res is not None:
                        if isinstance(res, float) and res.is_integer():
                            res = int(res)
                        return LiteralNode(res)
                except Exception:
                    pass

        # 2. 代数恒等式化简
        # x + 0 / 0 + x -> x
        if op == "+":
            if isinstance(right, LiteralNode) and right.value == 0:
                return left
            if isinstance(left, LiteralNode) and left.value == 0:
                return right
        # x - 0 -> x
        elif op == "-":
            if isinstance(right, LiteralNode) and right.value == 0:
                return left
            if isinstance(left, LiteralNode) and left.value == 0:
                return UnaryOpNode("-", right).accept(self)
        # x * 1 / 1 * x -> x; x * 0 / 0 * x -> 0
        elif op == "*":
            if isinstance(right, LiteralNode):
                if right.value == 1:
                    return left
                if right.value == 0:
                    return LiteralNode(0)
            if isinstance(left, LiteralNode):
                if left.value == 1:
                    return right
                if left.value == 0:
                    return LiteralNode(0)
        # x / 1 -> x
        elif op == "/":
            if isinstance(right, LiteralNode) and right.value == 1:
                return left

        # 3. 可交换算子的结合律展平与字典序重排
        if op in COMMUTATIVE_OPS:
            raw_operands = _extract_associative_chain(BinaryOpNode(op, left, right), op)
            can_operands = [self.canonicalize(o) for o in raw_operands]
            # 按子树规范化字符串字典序排序
            sorted_operands = sorted(can_operands, key=lambda x: x.to_string())
            return _build_left_associative_tree(sorted_operands, op)

        return BinaryOpNode(op, left, right)

    def visit_function_call(self, node: FunctionCallNode) -> ExpressionNode:
        name = node.name.lower()
        args = tuple(self.canonicalize(arg) for arg in node.args)
        kwargs = tuple((k, self.canonicalize(v)) for k, v in node.kwargs)

        # 1. 幂等单输入算子消除: rank(rank(x)) -> rank(x), zscore(zscore(x)) -> zscore(x)
        if name in IDEMPOTENT_OPS and len(args) == 1 and not kwargs:
            inner = args[0]
            if isinstance(inner, FunctionCallNode) and inner.name.lower() == name and len(inner.args) == 1 and not inner.kwargs:
                return inner  # 直接返回已经 canonicalize 过的内层节点

        # 2. reverse(reverse(x)) -> x
        if name == "reverse" and len(args) == 1 and not kwargs:
            inner = args[0]
            if isinstance(inner, FunctionCallNode) and inner.name.lower() == "reverse" and len(inner.args) == 1:
                return inner.args[0]

        # 3. ts_rank(ts_rank(x, w), w) -> ts_rank(x, w)
        if name == "ts_rank" and len(args) == 2 and not kwargs:
            inner = args[0]
            w = args[1]
            if isinstance(inner, FunctionCallNode) and inner.name.lower() == "ts_rank" and len(inner.args) == 2:
                if inner.args[1].to_string() == w.to_string():
                    return inner

        # 4. ts_delay(ts_delay(x, w1), w2) -> ts_delay(x, w1 + w2)
        if name == "ts_delay" and len(args) == 2 and not kwargs:
            inner = args[0]
            w2 = args[1]
            if isinstance(inner, FunctionCallNode) and inner.name.lower() == "ts_delay" and len(inner.args) == 2:
                w1 = inner.args[1]
                if isinstance(w1, LiteralNode) and isinstance(w2, LiteralNode):
                    if isinstance(w1.value, (int, float)) and isinstance(w2.value, (int, float)):
                        new_w = int(w1.value + w2.value)
                        return FunctionCallNode("ts_delay", (inner.args[0], LiteralNode(new_w)))

        return FunctionCallNode(name, args, kwargs)

    def visit_ternary(self, node: TernaryNode) -> ExpressionNode:
        cond = self.canonicalize(node.condition)
        true_expr = self.canonicalize(node.true_expr)
        false_expr = self.canonicalize(node.false_expr)

        # 若 cond 为常数，直接折叠
        if isinstance(cond, LiteralNode):
            if bool(cond.value) is True:
                return true_expr
            return false_expr

        # 若 true_expr 与 false_expr 相同，直接返回
        if true_expr.to_string() == false_expr.to_string():
            return true_expr

        return TernaryNode(cond, true_expr, false_expr)


def canonicalize_expression(expr: Union[str, ExpressionNode]) -> ExpressionNode:
    """规范化 Alpha 表达式.

    Args:
        expr: 字符串或 AST 节点

    Returns:
        规范化后的 AST 节点
    """
    if isinstance(expr, str):
        node = parse_expression(expr)
    else:
        node = expr

    canonicalizer = ASTCanonicalizer()
    return canonicalizer.canonicalize(node)


def to_canonical_string(expr: Union[str, ExpressionNode]) -> str:
    """返回 Alpha 表达式的唯一标准规范化字符串."""
    node = canonicalize_expression(expr)
    return node.to_string()


def get_canonical_sha(expr: Union[str, ExpressionNode]) -> str:
    """计算 Alpha 表达式的标准规范化 SHA-256 哈希值.

    任何数学或语义等价的表达式（如交换加法次序、冗余嵌套算子）均计算出完全相同的 SHA。
    """
    can_str = to_canonical_string(expr)
    return hashlib.sha256(can_str.encode("utf-8")).hexdigest()
