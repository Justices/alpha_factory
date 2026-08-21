"""多维实战红线审查规则集 (Submission Rubrics).

基于 20 篇高水平量化顾问实战语料与平台红线沉淀:
  1. economic_foundation: 经济学机理审查 (必须包含清晰因果逻辑 rationale)
  2. implementation_simplicity: AST 语法树简洁性与规范周期窗口审查
  3. diversification_and_correlation: 存量自相关与产线相关性硬/软约束
  4. template_generalizability: 模板通用性与可复用性审查
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set

from alpha_operator_framework.domain.ast import (
    ExpressionNode,
    FunctionCallNode,
    LiteralNode,
    TernaryNode,
    VariableNode,
    extract_ast_fields,
    parse_expression,
)


class RubricSeverity(str, Enum):
    """审查违规严重等级."""

    BLOCK = "block"      # 阻断性违规 (禁止提交)
    REVIEW = "review"    # 需人工复核/微调
    INFO = "info"        # 提示性建议


class RubricStatus(str, Enum):
    """单项审查结果状态."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class RubricResult:
    """单项红线审查结果."""

    rubric_id: str
    title: str
    severity: RubricSeverity
    status: RubricStatus
    reason: str
    action_hint: str = ""


# 平台推荐的标准规范周期窗口
CANONICAL_WINDOWS: Set[int] = {
    1, 2, 3, 4, 5, 10, 15, 20, 21, 22, 30, 40, 60, 63, 66, 120, 126, 160, 240, 252, 500
}


def _count_ast_nodes(node: ExpressionNode) -> Dict[str, Any]:
    """递归遍历 AST 语法树，提取算子数量、三元条件数、所有出现的时序窗口参数."""
    stats: Dict[str, Any] = {
        "operator_count": 0,
        "ternary_count": 0,
        "windows_used": set(),
        "function_names": set(),
    }

    def _traverse(n: ExpressionNode):
        if isinstance(n, FunctionCallNode):
            stats["operator_count"] += 1
            stats["function_names"].add(n.name)
            # 检查时序窗口参数 (如果是 ts_ 算子且参数为整数字面量)
            is_ts_op = n.name.startswith("ts_")
            for idx, arg in enumerate(n.args):
                if is_ts_op and idx >= 1 and isinstance(arg, LiteralNode) and isinstance(arg.value, (int, float)):
                    if float(arg.value).is_integer():
                        stats["windows_used"].add(int(arg.value))
                _traverse(arg)
            for _, kw_val in n.kwargs:
                _traverse(kw_val)
        elif isinstance(n, TernaryNode):
            stats["ternary_count"] += 1
            stats["operator_count"] += 1
            _traverse(n.condition)
            _traverse(n.true_expr)
            _traverse(n.false_expr)
        elif hasattr(n, "operand"):  # UnaryOpNode
            stats["operator_count"] += 1
            _traverse(getattr(n, "operand"))
        elif hasattr(n, "left") and hasattr(n, "right"):  # BinaryOpNode
            stats["operator_count"] += 1
            _traverse(getattr(n, "left"))
            _traverse(getattr(n, "right"))

    _traverse(node)
    return stats


def evaluate_implementation_simplicity(
    expression: str,
    max_operators: int = 20,
    max_conditionals: int = 2,
    max_distinct_windows: int = 5,
) -> RubricResult:
    """审查表达式简洁性与周期规范性 (implementation_simplicity)."""
    try:
        ast = parse_expression(expression)
        stats = _count_ast_nodes(ast)
    except Exception as e:
        return RubricResult(
            rubric_id="implementation_simplicity",
            title="Implementation simplicity",
            severity=RubricSeverity.REVIEW,
            status=RubricStatus.WARN,
            reason=f"表达式语法解析异常: {e}",
            action_hint="请检查表达式语法是否符合标准 AST 格式",
        )

    op_count = stats["operator_count"]
    cond_count = stats["ternary_count"]
    windows = stats["windows_used"]

    # 1. 检查算子堆叠
    if op_count > max_operators:
        return RubricResult(
            rubric_id="implementation_simplicity",
            title="Implementation simplicity",
            severity=RubricSeverity.REVIEW,
            status=RubricStatus.FAIL,
            reason=f"算子堆叠过多 ({op_count} > 上限 {max_operators})，存在过度参数拟合风险",
            action_hint="简化公式结构，剥离冗余算子层级",
        )

    # 2. 检查多重条件嵌套
    if cond_count > max_conditionals:
        return RubricResult(
            rubric_id="implementation_simplicity",
            title="Implementation simplicity",
            severity=RubricSeverity.REVIEW,
            status=RubricStatus.FAIL,
            reason=f"条件分支过多 ({cond_count} > 上限 {max_conditionals})，容易造成策略跳跃",
            action_hint="减少 ? : 条件分支嵌套，改用连续平滑算子",
        )

    # 3. 检查非规范时序窗口
    non_canonical = [w for w in windows if w not in CANONICAL_WINDOWS and w > 0]
    if len(windows) > max_distinct_windows:
        return RubricResult(
            rubric_id="implementation_simplicity",
            title="Implementation simplicity",
            severity=RubricSeverity.REVIEW,
            status=RubricStatus.WARN,
            reason=f"使用了过多不同的时序窗口 ({len(windows)} > {max_distinct_windows})",
            action_hint="统一时序滚动周期参数",
        )

    if non_canonical:
        return RubricResult(
            rubric_id="implementation_simplicity",
            title="Implementation simplicity",
            severity=RubricSeverity.INFO,
            status=RubricStatus.WARN,
            reason=f"包含非标准周期窗口: {non_canonical} (推荐使用 1, 5, 10, 20, 60, 120, 252)",
            action_hint="建议将周期参数调整为平台规范标准窗口",
        )

    return RubricResult(
        rubric_id="implementation_simplicity",
        title="Implementation simplicity",
        severity=RubricSeverity.REVIEW,
        status=RubricStatus.PASS,
        reason=f"表达紧凑规范 (算子数={op_count}, 条件数={cond_count}, 窗口合规)",
    )


def evaluate_economic_foundation(meta_or_details: Dict[str, Any]) -> RubricResult:
    """审查经济学机理基础 (economic_foundation)."""
    rationale = str(
        meta_or_details.get("rationale")
        or meta_or_details.get("idea_summary")
        or meta_or_details.get("meta", {}).get("rationale")
        or meta_or_details.get("meta", {}).get("paper_title")
        or ""
    ).strip()

    if len(rationale) < 8:
        return RubricResult(
            rubric_id="economic_foundation",
            title="Economic foundation",
            severity=RubricSeverity.REVIEW,
            status=RubricStatus.WARN,
            reason="缺少清晰的金融经济学因果逻辑说明 (rationale)",
            action_hint="请补充该因子在市场摩擦/行为金融/信息不对称方面的理论支撑",
        )

    return RubricResult(
        rubric_id="economic_foundation",
        title="Economic foundation",
        severity=RubricSeverity.REVIEW,
        status=RubricStatus.PASS,
        reason="具备明确的经济学超额收益机理说明",
    )


def evaluate_diversification_and_correlation(details: Dict[str, Any]) -> RubricResult:
    """审查相关性纪律 (diversification_and_correlation)."""
    pc = float(details.get("pc_value") or details.get("prodCorrelation") or 0.0)
    sc = float(details.get("sc_value") or details.get("selfCorrelation") or 0.0)

    if pc >= 0.70:
        return RubricResult(
            rubric_id="diversification_and_correlation",
            title="Diversification and correlation",
            severity=RubricSeverity.BLOCK,
            status=RubricStatus.FAIL,
            reason=f"与存量产线 Alpha 相关性过高 (ProdCorrelation={pc:.2f} >= 0.70)",
            action_hint="施加正交残差化或追加行业中性化 group_neutralize 剥离共线性",
        )

    if sc >= 0.70:
        return RubricResult(
            rubric_id="diversification_and_correlation",
            title="Diversification and correlation",
            severity=RubricSeverity.BLOCK,
            status=RubricStatus.FAIL,
            reason=f"与个人存量提交库自相关过高 (SelfCorrelation={sc:.2f} >= 0.70)",
            action_hint="调整核心特征字段或改变时序算子族",
        )

    return RubricResult(
        rubric_id="diversification_and_correlation",
        title="Diversification and correlation",
        severity=RubricSeverity.REVIEW,
        status=RubricStatus.PASS,
        reason=f"相关性处于安全区间 (PC={pc:.2f}, SC={sc:.2f})",
    )


def evaluate_all_rubrics(
    expression: str,
    details: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> List[RubricResult]:
    """批量执行全部实战红线审查."""
    combined_meta = {**details, **(meta or {})}
    return [
        evaluate_economic_foundation(combined_meta),
        evaluate_implementation_simplicity(expression),
        evaluate_diversification_and_correlation(details),
    ]
