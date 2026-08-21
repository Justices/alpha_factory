"""论文公式到 AST 语法树编译器 (Paper to AST Translator).

功能:
  1. 将对齐真实字段后的论文公式编译为 AST 语法树
  2. 自动规范化 (Canonicalize)、消除代数冗余与语法校验
  3. 构建携带完整文献溯源元数据的 Task 任务对象
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from alpha_operator_framework.domain.ast import (
    canonicalize_expression,
    extract_ast_fields,
    to_canonical_string,
    validate_expression,
)
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.research.idea_extractor import PaperIdea


def _substitute_variables_in_formula(formula: str, var_map: Dict[str, str]) -> str:
    """精准替换公式中的变量标识符 (按单词边界匹配，避免子串误伤)."""
    result = formula
    # 按变量名长度降序替换，防止前缀冲突
    sorted_vars = sorted(var_map.keys(), key=len, reverse=True)

    for var in sorted_vars:
        replacement = var_map[var]
        pattern = r"\b" + re.escape(var) + r"\b"
        result = re.sub(pattern, replacement, result)

    return result


class PaperToASTTranslator:
    """论文公式到 AST 语法树编译器."""

    @staticmethod
    def translate_idea_to_tasks(
        idea: PaperIdea,
        grounded_variables: Dict[str, str],
        decay: Optional[float] = None,
    ) -> List[Task]:
        """将 PaperIdea 与对齐后的真实字段编译为可执行的 Task 任务列表.

        Args:
            idea: 提炼出的假说对象
            grounded_variables: 变量名 -> 真实字段 ID 映射
            decay: 衰减参数 (默认使用 idea.recommended_decay)

        Returns:
            生成的 Task 任务列表
        """
        substituted = _substitute_variables_in_formula(idea.abstract_formula, grounded_variables)
        actual_decay = float(decay if decay is not None else idea.recommended_decay)

        tasks: List[Task] = []

        try:
            # 1. AST 规范化与化简
            can_expr = to_canonical_string(substituted)
            # 2. 静态语义与类型校验
            val_res = validate_expression(can_expr)
            if not val_res.is_valid:
                # 尝试保底修复 (如添加 rank 包裹)
                fallback_expr = to_canonical_string(f"rank({substituted})")
                val_res = validate_expression(fallback_expr)
                if val_res.is_valid:
                    can_expr = fallback_expr
                else:
                    return []

            fields_used = tuple(sorted(extract_ast_fields(can_expr)))

            task = Task(
                expression=can_expr,
                template_index=0,
                family="literature",
                fields_per_alpha=len(fields_used),
                expression_origin=f"paper_{idea.category}",
                decay=actual_decay,
                base_fields=fields_used,
                meta={
                    "paper_title": idea.title,
                    "category": idea.category,
                    "rationale": idea.rationale,
                    "source_reference": idea.source_reference,
                    "abstract_formula": idea.abstract_formula,
                    "grounded_variables": grounded_variables,
                },
            )
            tasks.append(task)

        except Exception:
            return []

        return tasks
