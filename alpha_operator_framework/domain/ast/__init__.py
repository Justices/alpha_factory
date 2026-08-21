"""Alpha AST 语法树模块 — 表达式解析、规范化去重与静态语义验证."""

from .nodes import (
    ASTVisitor,
    BinaryOpNode,
    ExpressionNode,
    FunctionCallNode,
    LiteralNode,
    TernaryNode,
    UnaryOpNode,
    VariableNode,
)
from .parser import parse_expression
from .canonicalizer import (
    ASTCanonicalizer,
    canonicalize_expression,
    get_canonical_sha,
    to_canonical_string,
)
from .validator import (
    ASTValidator,
    ValidationResult,
    extract_ast_fields,
    validate_expression,
)

__all__ = [
    # 节点
    "ASTVisitor",
    "ExpressionNode",
    "VariableNode",
    "LiteralNode",
    "UnaryOpNode",
    "BinaryOpNode",
    "FunctionCallNode",
    "TernaryNode",
    # 解析
    "parse_expression",
    # 规范化与哈希
    "ASTCanonicalizer",
    "canonicalize_expression",
    "to_canonical_string",
    "get_canonical_sha",
    # 校验
    "ASTValidator",
    "ValidationResult",
    "validate_expression",
    "extract_ast_fields",
]
