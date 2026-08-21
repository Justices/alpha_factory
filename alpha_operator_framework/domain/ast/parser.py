"""Alpha AST 解析器 — 将公式字符串解析为强类型 AST 节点树.

支持:
  1. 标准函数调用与多参数、关键字参数: ts_regression(x, y, 10, rettype=2)
  2. 四则运算与布尔比较: +, -, *, /, %, >, <, >=, <=, ==, !=
  3. 三元条件运算: cond ? true_val : false_val 与 Python if-else
  4. 负号与取反: -close, !cond
"""

from __future__ import annotations

import ast
import re
from typing import Any, List, Tuple

from alpha_operator_framework.domain.ast.nodes import (
    BinaryOpNode,
    ExpressionNode,
    FunctionCallNode,
    LiteralNode,
    TernaryNode,
    UnaryOpNode,
    VariableNode,
)


def _convert_ternary_syntax(expr_str: str) -> str:
    """将 C/BRAIN 风格三元表达式 `cond ? a : b` 转换为 Python 风格 `(a if cond else b)`."""
    # 递归/多轮转换处理可能存在的三元运算符
    if "?" not in expr_str:
        return expr_str

    # 简易而稳健的词法状态机解析三元问号与冒号匹配
    chars = list(expr_str)
    n = len(chars)

    def find_matching_colon(start_idx: int) -> int:
        depth_paren = 0
        depth_bracket = 0
        depth_q = 1
        for i in range(start_idx, n):
            c = chars[i]
            if c == "(":
                depth_paren += 1
            elif c == ")":
                depth_paren -= 1
            elif c == "[":
                depth_bracket += 1
            elif c == "]":
                depth_bracket -= 1
            elif depth_paren == 0 and depth_bracket == 0:
                if c == "?":
                    depth_q += 1
                elif c == ":":
                    depth_q -= 1
                    if depth_q == 0:
                        return i
        return -1

    # 寻找顶层或最内层 ?
    i = 0
    while i < len(chars):
        if chars[i] == "?":
            colon_idx = find_matching_colon(i + 1)
            if colon_idx != -1:
                # 提取 cond, true_branch, false_branch
                # 往前找 cond 的边界 (括号或逗号或开头)
                cond_start = i - 1
                depth_p = 0
                while cond_start >= 0:
                    c = chars[cond_start]
                    if c == ")":
                        depth_p += 1
                    elif c == "(":
                        if depth_p == 0:
                            cond_start += 1
                            break
                        depth_p -= 1
                    elif c == "," and depth_p == 0:
                        cond_start += 1
                        break
                    cond_start -= 1
                cond_start = max(0, cond_start)

                # 往后找 false_branch 的边界
                false_end = colon_idx + 1
                depth_p = 0
                while false_end < len(chars):
                    c = chars[false_end]
                    if c == "(":
                        depth_p += 1
                    elif c == ")":
                        if depth_p == 0:
                            break
                        depth_p -= 1
                    elif (c == "," or c == "?") and depth_p == 0:
                        break
                    false_end += 1

                cond_str = "".join(chars[cond_start:i]).strip()
                true_str = "".join(chars[i + 1:colon_idx]).strip()
                false_str = "".join(chars[colon_idx + 1:false_end]).strip()

                converted = f"({_convert_ternary_syntax(true_str)} if {_convert_ternary_syntax(cond_str)} else {_convert_ternary_syntax(false_str)})"
                chars = chars[:cond_start] + list(converted) + chars[false_end:]
                i = cond_start + len(converted)
                continue
        i += 1

    return "".join(chars)


class _PyASTConverter(ast.NodeVisitor):
    """将 Python 标准 AST 转换为 Alpha AST Node."""

    BIN_OP_MAP = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.Mod: "%",
        ast.Pow: "**",
        ast.BitAnd: "&&",
        ast.BitOr: "||",
        ast.And: "&&",
        ast.Or: "||",
    }

    COMPARE_OP_MAP = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    UNARY_OP_MAP = {
        ast.USub: "-",
        ast.UAdd: "+",
        ast.Not: "!",
        ast.Invert: "!",
    }

    def convert(self, node: ast.AST) -> ExpressionNode:
        return self.visit(node)

    def visit_Expression(self, node: ast.Expression) -> ExpressionNode:
        return self.visit(node.body)

    def visit_Name(self, node: ast.Name) -> ExpressionNode:
        return VariableNode(node.id)

    def visit_Constant(self, node: ast.Constant) -> ExpressionNode:
        return LiteralNode(node.value)

    # 兼容 Python 3.7 及更早版本的 Num / Str / NameConstant
    def visit_Num(self, node: Any) -> ExpressionNode:
        return LiteralNode(node.n)

    def visit_Str(self, node: Any) -> ExpressionNode:
        return LiteralNode(node.s)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ExpressionNode:
        op_cls = type(node.op)
        op_str = self.UNARY_OP_MAP.get(op_cls, "-")
        operand = self.visit(node.operand)

        # 负号与常量合并: - (5) -> -5
        if op_str == "-" and isinstance(operand, LiteralNode) and isinstance(operand.value, (int, float)):
            return LiteralNode(-operand.value)

        return UnaryOpNode(op_str, operand)

    def visit_BinOp(self, node: ast.BinOp) -> ExpressionNode:
        op_cls = type(node.op)
        op_str = self.BIN_OP_MAP.get(op_cls, "+")
        left = self.visit(node.left)
        right = self.visit(node.right)
        return BinaryOpNode(op_str, left, right)

    def visit_BoolOp(self, node: ast.BoolOp) -> ExpressionNode:
        op_cls = type(node.op)
        op_str = self.BIN_OP_MAP.get(op_cls, "&&")
        # 链式 And/Or 转换为二叉树
        values = [self.visit(val) for val in node.values]
        res = values[0]
        for v in values[1:]:
            res = BinaryOpNode(op_str, res, v)
        return res

    def visit_Compare(self, node: ast.Compare) -> ExpressionNode:
        left = self.visit(node.left)
        res = None
        current_left = left
        for op, comparator in zip(node.ops, node.comparators):
            op_cls = type(op)
            op_str = self.COMPARE_OP_MAP.get(op_cls, "==")
            right = self.visit(comparator)
            cmp_node = BinaryOpNode(op_str, current_left, right)
            if res is None:
                res = cmp_node
            else:
                res = BinaryOpNode("&&", res, cmp_node)
            current_left = right
        return res or left

    def visit_Call(self, node: ast.Call) -> ExpressionNode:
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = f"{node.func.value.id}.{node.func.attr}"
        else:
            func_name = str(node.func)

        args = tuple(self.visit(arg) for arg in node.args)
        kwargs = tuple((kw.arg or "", self.visit(kw.value)) for kw in node.keywords)
        return FunctionCallNode(func_name, args, kwargs)

    def visit_IfExp(self, node: ast.IfExp) -> ExpressionNode:
        cond = self.visit(node.test)
        true_expr = self.visit(node.body)
        false_expr = self.visit(node.orelse)
        return TernaryNode(cond, true_expr, false_expr)

    def generic_visit(self, node: ast.AST) -> ExpressionNode:
        raise ValueError(f"Unsupported syntax construct in Alpha expression: {ast.dump(node)}")


def parse_expression(expr_str: str) -> ExpressionNode:
    """将 Alpha 表达式字符串解析为 AST Node.

    Args:
        expr_str: 表达式字符串，如 "group_neutralize(ts_rank(close, 22), industry)"

    Returns:
        ExpressionNode 抽象语法树根节点
    """
    cleaned = expr_str.strip()
    if not cleaned:
        raise ValueError("Cannot parse empty expression")

    # 预处理三元表达式与逻辑符号
    converted = _convert_ternary_syntax(cleaned)

    # 替换可能出现的非 Python 比较符与逻辑符
    # 比如 && -> & , || -> |
    converted = re.sub(r'&&', '&', converted)
    converted = re.sub(r'\|\|', '|', converted)
    converted = re.sub(r'!(?!=)', ' not ', converted)

    try:
        py_ast = ast.parse(converted, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Failed to parse Alpha expression '{expr_str}': {e}") from e

    converter = _PyASTConverter()
    return converter.convert(py_ast)
