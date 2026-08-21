"""Alpha AST 节点定义 — 强类型抽象语法树.

定义 Alpha 表达式的节点体系，支持四则运算、函数调用、三元条件与常量折叠。
所有节点均为不可变或提供统一的遍历与字符串化接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple, Union


class ASTVisitor(ABC):
    """AST 访问者抽象基类."""

    @abstractmethod
    def visit_variable(self, node: VariableNode) -> Any:
        pass

    @abstractmethod
    def visit_literal(self, node: LiteralNode) -> Any:
        pass

    @abstractmethod
    def visit_unary_op(self, node: UnaryOpNode) -> Any:
        pass

    @abstractmethod
    def visit_binary_op(self, node: BinaryOpNode) -> Any:
        pass

    @abstractmethod
    def visit_function_call(self, node: FunctionCallNode) -> Any:
        pass

    @abstractmethod
    def visit_ternary(self, node: TernaryNode) -> Any:
        pass


@dataclass(frozen=True)
class ExpressionNode(ABC):
    """AST 表达式节点基类."""

    @abstractmethod
    def accept(self, visitor: ASTVisitor) -> Any:
        """接受访问者."""
        pass

    @abstractmethod
    def to_string(self) -> str:
        """转为标准格式字符串."""
        pass

    def __str__(self) -> str:
        return self.to_string()


@dataclass(frozen=True)
class VariableNode(ExpressionNode):
    """变量/字段节点 (如 close, volume, industry)."""

    name: str

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_variable(self)

    def to_string(self) -> str:
        return self.name


@dataclass(frozen=True)
class LiteralNode(ExpressionNode):
    """常量节点 (如 10, 0.5, 'industry')."""

    value: Union[int, float, str, bool]

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_literal(self)

    def to_string(self) -> str:
        if isinstance(self.value, str):
            return f"'{self.value}'"
        if isinstance(self.value, float):
            # 去除冗余的小数点 0，如 10.0 -> 10.0，整数形式直接显示
            if self.value.is_integer():
                return f"{int(self.value)}"
            return f"{self.value}"
        return str(self.value)


@dataclass(frozen=True)
class UnaryOpNode(ExpressionNode):
    """一元操作符节点 (如 -x, +x, !x)."""

    op: str  # "-", "+", "!"
    operand: ExpressionNode

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_unary_op(self)

    def to_string(self) -> str:
        inner = self.operand.to_string()
        if isinstance(self.operand, (BinaryOpNode, TernaryNode)):
            inner = f"({inner})"
        return f"{self.op}{inner}"


@dataclass(frozen=True)
class BinaryOpNode(ExpressionNode):
    """二元操作符节点 (如 a + b, a / b, a > b)."""

    op: str  # "+", "-", "*", "/", "%", ">", "<", ">=", "<=", "==", "!=", "&&", "||"
    left: ExpressionNode
    right: ExpressionNode

    # 优先级映射 (用于智能括号格式化)
    PRECEDENCE = {
        "||": 1, "or": 1,
        "&&": 2, "and": 2,
        "==": 3, "!=": 3, "<": 3, "<=": 3, ">": 3, ">=": 3,
        "+": 4, "-": 4,
        "*": 5, "/": 5, "%": 5,
        "**": 6, "^": 6,
    }

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_binary_op(self)

    def to_string(self) -> str:
        my_prec = self.PRECEDENCE.get(self.op, 0)

        left_str = self.left.to_string()
        if isinstance(self.left, BinaryOpNode):
            left_prec = self.PRECEDENCE.get(self.left.op, 0)
            if left_prec < my_prec:
                left_str = f"({left_str})"
        elif isinstance(self.left, TernaryNode):
            left_str = f"({left_str})"

        right_str = self.right.to_string()
        if isinstance(self.right, BinaryOpNode):
            right_prec = self.PRECEDENCE.get(self.right.op, 0)
            # 结合律处理：减法与除法右侧同优先级需加括号，如 a - (b - c)
            if right_prec < my_prec or (right_prec == my_prec and self.op in ("-", "/", "%")):
                right_str = f"({right_str})"
        elif isinstance(self.right, TernaryNode):
            right_str = f"({right_str})"

        return f"{left_str} {self.op} {right_str}"


@dataclass(frozen=True)
class FunctionCallNode(ExpressionNode):
    """函数调用节点 (如 ts_rank(close, 10), group_neutralize(x, industry))."""

    name: str
    args: Tuple[ExpressionNode, ...]
    kwargs: Tuple[Tuple[str, ExpressionNode], ...] = ()

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_function_call(self)

    def to_string(self) -> str:
        arg_strs = [arg.to_string() for arg in self.args]
        kwarg_strs = [f"{k}={v.to_string()}" for k, v in self.kwargs]
        all_args = ", ".join(arg_strs + kwarg_strs)
        return f"{self.name}({all_args})"


@dataclass(frozen=True)
class TernaryNode(ExpressionNode):
    """三元条件节点 (cond ? true_expr : false_expr)."""

    condition: ExpressionNode
    true_expr: ExpressionNode
    false_expr: ExpressionNode

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_ternary(self)

    def to_string(self) -> str:
        return f"({self.condition.to_string()} ? {self.true_expr.to_string()} : {self.false_expr.to_string()})"
