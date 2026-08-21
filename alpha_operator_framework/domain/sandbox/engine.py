"""本地轻量向量化信号诊断器 (SignalDiagnosticEngine / SandboxEngine).

核心定位与边界:
  1. 本模块是【快速截面 IC 与单调性信号诊断工具】，专用于生成阶段的初步离线初筛
  2. 计算 Rank IC, IC IR, 预测前向收益 Sharpe, 理论日均换手率 (Turnover) 与 Fitness
  3. ⚠️ 边界说明: 本诊断器不计真实交易摩擦、滑点、借券成本与风险模型中性化，
     其产出的指标属于 EvidenceLevel.SANDBOX_DIAGNOSTIC，绝对不可作为提交评证或与实盘平台混排！
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union
import numpy as np

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
from alpha_operator_framework.domain.sandbox.market_data import (
    MarketDataCrossSection,
    generate_synthetic_market_data,
)
from alpha_operator_framework.domain.sandbox.ops import (
    SANDBOX_OPS_MAP,
    cs_rank,
    cs_scale,
    cs_zscore,
    group_neutralize,
)


@dataclass
class SandboxMetrics:
    """沙盒回测评估指标."""

    expression: str
    rank_ic: float = 0.0
    ic_std: float = 0.0
    ic_ir: float = 0.0
    annualized_return: float = 0.0
    sharpe: float = 0.0
    turnover: float = 0.0
    fitness: float = 0.0
    coverage: float = 0.0
    is_valid: bool = False
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expression": self.expression,
            "rank_ic": round(self.rank_ic, 4),
            "ic_ir": round(self.ic_ir, 3),
            "sharpe": round(self.sharpe, 3),
            "turnover": round(self.turnover, 3),
            "fitness": round(self.fitness, 3),
            "coverage": round(self.coverage, 3),
            "is_valid": self.is_valid,
            "error_message": self.error_message,
        }


class _ASTEvaluator(ASTVisitor):
    """AST 在截面矩阵上的求值访问者."""

    def __init__(self, market_data: MarketDataCrossSection):
        self.data = market_data
        self.T, self.N = market_data.shape

    def evaluate(self, node: ExpressionNode) -> Any:
        return node.accept(self)

    def visit_variable(self, node: VariableNode) -> np.ndarray:
        field_mat = self.data.get_field(node.name)
        if field_mat is None:
            raise KeyError(f"Field '{node.name}' not found in Sandbox market data")
        return field_mat.copy()

    def visit_literal(self, node: LiteralNode) -> Any:
        return node.value

    def visit_unary_op(self, node: UnaryOpNode) -> Any:
        operand = self.evaluate(node.operand)
        if isinstance(operand, np.ndarray):
            if node.op == "-":
                return -operand
            elif node.op == "!":
                return (~(operand.astype(bool))).astype(np.float64)
            return operand
        else:
            if node.op == "-":
                return -operand
            elif node.op == "!":
                return not bool(operand)
            return operand

    def visit_binary_op(self, node: BinaryOpNode) -> Any:
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        # 广播标量或矩阵
        if isinstance(left, (int, float)) and isinstance(right, np.ndarray):
            left = np.full_like(right, float(left))
        elif isinstance(right, (int, float)) and isinstance(left, np.ndarray):
            right = np.full_like(left, float(right))

        op = node.op
        if op == "+":
            return left + right
        elif op == "-":
            return left - right
        elif op == "*":
            return left * right
        elif op == "/":
            if isinstance(right, np.ndarray):
                with np.errstate(divide="ignore", invalid="ignore"):
                    res = left / right
                    res[np.isinf(res)] = np.nan
                    return res
            return left / right if right != 0 else np.nan
        elif op == "%":
            return left % right
        elif op in ("**", "^"):
            return left ** right
        elif op == ">":
            return (left > right).astype(np.float64)
        elif op == "<":
            return (left < right).astype(np.float64)
        elif op == ">=":
            return (left >= right).astype(np.float64)
        elif op == "<=":
            return (left <= right).astype(np.float64)
        elif op == "==":
            return (left == right).astype(np.float64)
        elif op == "!=":
            return (left != right).astype(np.float64)
        elif op in ("&&", "&"):
            return (left.astype(bool) & right.astype(bool)).astype(np.float64)
        elif op in ("||", "|"):
            return (left.astype(bool) | right.astype(bool)).astype(np.float64)

        raise NotImplementedError(f"Unsupported binary operator: {op}")

    def visit_function_call(self, node: FunctionCallNode) -> Any:
        name = node.name.lower()
        func = SANDBOX_OPS_MAP.get(name)
        if func is None:
            raise NotImplementedError(f"Operator '{name}' not implemented in Sandbox Engine")

        # 针对 group 算子做特殊参数匹配 (如 group_neutralize(x, industry))
        if name.startswith("group_"):
            if len(node.args) >= 2:
                arg0 = self.evaluate(node.args[0])
                group_arg = node.args[1]
                if isinstance(group_arg, VariableNode):
                    group_mat = self.data.get_field(group_arg.name)
                elif isinstance(group_arg, LiteralNode) and isinstance(group_arg.value, str):
                    group_mat = self.data.get_field(group_arg.value)
                else:
                    group_mat = self.evaluate(group_arg)

                if group_mat is None:
                    group_mat = self.data.groups

                return func(arg0, group_mat)

        eval_args = [self.evaluate(arg) for arg in node.args]
        eval_kwargs = {k: self.evaluate(v) for k, v in node.kwargs}
        return func(*eval_args, **eval_kwargs)

    def visit_ternary(self, node: TernaryNode) -> Any:
        cond = self.evaluate(node.condition)
        true_val = self.evaluate(node.true_expr)
        false_val = self.evaluate(node.false_expr)

        if isinstance(cond, np.ndarray):
            mask = cond.astype(bool)
            if not isinstance(true_val, np.ndarray):
                true_val = np.full_like(cond, true_val)
            if not isinstance(false_val, np.ndarray):
                false_val = np.full_like(cond, false_val)
            return np.where(mask, true_val, false_val)
        else:
            return true_val if bool(cond) else false_val


class SandboxEngine:
    """本地轻量向量化沙盒仿真器."""

    def __init__(self, market_data: Optional[MarketDataCrossSection] = None):
        self.data = market_data or generate_synthetic_market_data()

    def evaluate_alpha_matrix(self, expr: Union[str, ExpressionNode]) -> np.ndarray:
        """在当前市场数据截面上计算 Alpha 矩阵 (Shape: [T, N])."""
        if isinstance(expr, str):
            ast_node = parse_expression(expr)
        else:
            ast_node = expr

        evaluator = _ASTEvaluator(self.data)
        res = evaluator.evaluate(ast_node)
        if not isinstance(res, np.ndarray):
            res = np.full(self.data.shape, float(res), dtype=np.float64)
        return res

    def evaluate_metrics(self, expr: Union[str, ExpressionNode]) -> SandboxMetrics:
        """评估单个 Alpha 表达式的性能指标."""
        expr_str = expr if isinstance(expr, str) else expr.to_string()

        try:
            alpha_mat = self.evaluate_alpha_matrix(expr)
        except Exception as e:
            return SandboxMetrics(expression=expr_str, is_valid=False, error_message=str(e))

        T, N = alpha_mat.shape
        fwd_ret = self.data.forward_returns
        if fwd_ret is None:
            return SandboxMetrics(expression=expr_str, is_valid=False, error_message="No forward returns provided")

        # 检查有效值
        valid_cnt = np.sum(~np.isnan(alpha_mat))
        total_cnt = T * N
        coverage = float(valid_cnt / total_cnt)
        if coverage < 0.1:
            return SandboxMetrics(expression=expr_str, coverage=coverage, is_valid=False, error_message="Signal coverage < 10%")

        # 1. 计算截面 Rank IC
        daily_ics = []
        for t in range(T - 1):
            a_row = alpha_mat[t]
            r_row = fwd_ret[t]
            mask = ~np.isnan(a_row) & ~np.isnan(r_row)
            if np.sum(mask) >= 5:
                a_valid = a_row[mask]
                r_valid = r_row[mask]
                # Spearman rank correlation
                a_rank = a_valid.argsort().argsort()
                r_rank = r_valid.argsort().argsort()
                corr_mat = np.corrcoef(a_rank, r_rank)
                if not np.isnan(corr_mat[0, 1]):
                    daily_ics.append(corr_mat[0, 1])

        if not daily_ics:
            return SandboxMetrics(expression=expr_str, coverage=coverage, is_valid=False, error_message="Insufficient data for IC calculation")

        daily_ics = np.array(daily_ics, dtype=np.float64)
        mean_ic = float(np.mean(daily_ics))
        std_ic = float(np.std(daily_ics))
        ic_ir = float((mean_ic / (std_ic + 1e-8)) * np.sqrt(252))

        # 2. 模拟长短对冲多空策略 (中性化 + 归一化权重)
        weights = cs_scale(cs_zscore(alpha_mat))  # shape: (T, N)
        daily_pnls = []
        turnovers = []

        for t in range(1, T - 1):
            w_prev = weights[t - 1]
            ret_curr = fwd_ret[t - 1]
            w_curr = weights[t]

            valid_w = ~np.isnan(w_prev) & ~np.isnan(ret_curr)
            if np.sum(valid_w) > 0:
                pnl = np.sum(w_prev[valid_w] * ret_curr[valid_w])
                daily_pnls.append(pnl)

            # 换手率: 0.5 * sum(|w_t - w_{t-1}|)
            w_p = np.nan_to_num(w_prev, nan=0.0)
            w_c = np.nan_to_num(w_curr, nan=0.0)
            to = 0.5 * np.sum(np.abs(w_c - w_p))
            turnovers.append(to)

        daily_pnls = np.array(daily_pnls, dtype=np.float64)
        mean_pnl = float(np.mean(daily_pnls))
        std_pnl = float(np.std(daily_pnls))
        ann_return = mean_pnl * 252
        sharpe = float((mean_pnl / (std_pnl + 1e-8)) * np.sqrt(252))
        avg_turnover = float(np.mean(turnovers)) if turnovers else 0.0

        # Fitness = Sharpe * sqrt(|AnnualReturn| / max(Turnover, 0.01))
        fitness = float(sharpe * np.sqrt(max(abs(ann_return), 1e-4) / max(avg_turnover, 0.01)))

        return SandboxMetrics(
            expression=expr_str,
            rank_ic=mean_ic,
            ic_std=std_ic,
            ic_ir=ic_ir,
            annualized_return=ann_return,
            sharpe=sharpe,
            turnover=avg_turnover,
            fitness=fitness,
            coverage=coverage,
            is_valid=True,
        )

    def batch_evaluate(
        self,
        expressions: Sequence[Union[str, ExpressionNode]],
    ) -> List[SandboxMetrics]:
        """批量高速回测评估多个 Alpha 表达式."""
        return [self.evaluate_metrics(expr) for expr in expressions]


def evaluate_expression_local(
    expr: Union[str, ExpressionNode],
    market_data: Optional[MarketDataCrossSection] = None,
) -> SandboxMetrics:
    """本地沙盒单表达式便捷评估."""
    engine = SandboxEngine(market_data=market_data)
    return engine.evaluate_metrics(expr)


# 规范化别名定义 (清晰划分诊断器边界)
SignalDiagnosticEngine = SandboxEngine
SignalDiagnosticMetrics = SandboxMetrics

