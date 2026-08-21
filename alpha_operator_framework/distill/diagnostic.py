"""Alpha 故障自动诊断与归因分析器 (Failure Diagnostic Engine).

功能:
  1. 对未通过质量门或回测失败的 Alpha 进行精确病因归类
  2. 分析高换手、子宇宙失效、高相关性、边缘夏普等具体成因
  3. 输出针对性的 AST 突变修复建议清单
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class FailureMode(str, Enum):
    """Alpha 失败模式枚举."""

    HIGH_TURNOVER = "high_turnover"                      # 换手率过高 (> 70%)
    LOW_TURNOVER = "low_turnover"                        # 换手率过低 (< 1%)
    LOW_SUB_UNIVERSE_SHARPE = "low_sub_universe_sharpe"  # 子宇宙表现坍塌 (大盘股/小盘股分化严重)
    PROD_CORRELATION = "prod_correlation"                # 与存量已提交 Alpha 发生高相关冲突 (> 70%)
    MARGINAL_SHARPE = "marginal_sharpe"                  # 边缘夏普 (1.0 <= Sharpe < 1.25, 具备改造潜力)
    LOW_FITNESS = "low_fitness"                          # Fitness 未达标 (< 1.0)
    NEGATIVE_SHARPE = "negative_sharpe"                  # 信号反向 (Sharpe < -1.0)
    UNSPECIFIED = "unspecified"


@dataclass
class FailureDiagnosis:
    """Alpha 故障诊断结果报告."""

    alpha_id: str
    expression: str
    primary_cause: FailureMode
    all_modes: List[FailureMode] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    repair_recommendations: List[str] = field(default_factory=list)

    @property
    def is_repairable(self) -> bool:
        """是否属于具备修复潜力的因子 (非纯随机垃圾因子)."""
        return self.primary_cause in (
            FailureMode.HIGH_TURNOVER,
            FailureMode.LOW_SUB_UNIVERSE_SHARPE,
            FailureMode.MARGINAL_SHARPE,
            FailureMode.PROD_CORRELATION,
            FailureMode.NEGATIVE_SHARPE,
        )

    @property
    def summary(self) -> str:
        """诊断总结描述."""
        recs = ", ".join(self.repair_recommendations) if self.repair_recommendations else "保持观察"
        p_val = self.primary_cause.value if hasattr(self.primary_cause, "value") else str(self.primary_cause)
        return f"主因: {p_val}; 建议: {recs}"


def diagnose_alpha_failure(
    alpha_row: Dict[str, Any],
    checks: Optional[List[Dict[str, Any]]] = None,
) -> FailureDiagnosis:
    """对单个 Alpha 回测记录进行病因自动诊断与归因.

    Args:
        alpha_row: Alpha 详情字典 (包含 sharpe, fitness, turnover, pc_value, expression 等)
        checks: 平台 check 检查项数组 (可选)

    Returns:
        FailureDiagnosis 诊断报告
    """
    if isinstance(alpha_row, dict):
        alpha_id = str(alpha_row.get("alpha_id") or "")
        expr = str(alpha_row.get("expression") or "")
        sharpe = float(alpha_row.get("sharpe") or (alpha_row.get("is", {}) or {}).get("sharpe") or 0.0)
        fitness = float(alpha_row.get("fitness") or (alpha_row.get("is", {}) or {}).get("fitness") or 0.0)
        turnover = float(alpha_row.get("turnover") or (alpha_row.get("is", {}) or {}).get("turnover") or 0.0)
        pc = float(alpha_row.get("pc_value") or alpha_row.get("prodCorrelation") or 0.0)
    else:
        alpha_id = str(getattr(alpha_row, "alpha_id", "") or "")
        expr = str(getattr(alpha_row, "expression", "") or "")
        sharpe = float(getattr(alpha_row, "sharpe", 0.0) or 0.0)
        fitness = float(getattr(alpha_row, "fitness", 0.0) or 0.0)
        turnover = float(getattr(alpha_row, "turnover", 0.0) or 0.0)
        pc = float(getattr(alpha_row, "pc_value", 0.0) or 0.0)

    modes: List[FailureMode] = []
    recs: List[str] = []

    # 1. 检查信号是否显著反向
    if sharpe <= -1.0:
        modes.append(FailureMode.NEGATIVE_SHARPE)
        recs.append("invert_sign: 信号方向相反，施加整体负号 -1.0 * (expr)")

    # 2. 检查高换手
    if turnover > 0.70:
        modes.append(FailureMode.HIGH_TURNOVER)
        recs.append("smooth_decay: 换手率过高，建议在顶层包裹 ts_decay_linear 或放大差分窗口")

    # 3. 检查低换手
    if 0.0 < turnover < 0.01:
        modes.append(FailureMode.LOW_TURNOVER)
        recs.append("shorten_window: 换手率过低，建议缩短时序衰减与滚动窗口")

    # 4. 检查与存量相关性
    if pc >= 0.70:
        modes.append(FailureMode.PROD_CORRELATION)
        recs.append("orthogonalize: 与存量 Alpha 高相关，建议构建正交残差或做行业中性化")

    # 5. 检查子宇宙表现 (从 checks 中提取)
    if checks:
        for c in checks:
            if c.get("name") in ("LOW_SUB_UNIVERSE_SHARPE", "SUB_UNIVERSE_SHARPE") and c.get("result") == "FAIL":
                modes.append(FailureMode.LOW_SUB_UNIVERSE_SHARPE)
                recs.append("neutralize_subindustry: 子宇宙崩溃，建议追加细分行业 group_neutralize")
                break

    # 6. 检查边缘夏普
    if 1.0 <= sharpe < 1.25 and FailureMode.HIGH_TURNOVER not in modes:
        modes.append(FailureMode.MARGINAL_SHARPE)
        recs.append("nonlinear_scale: 边缘夏普，建议施加 signed_power(0.5) 压缩离群值或 ts_rank 排序")

    # 确定主要病因
    if FailureMode.NEGATIVE_SHARPE in modes:
        primary = FailureMode.NEGATIVE_SHARPE
    elif FailureMode.HIGH_TURNOVER in modes:
        primary = FailureMode.HIGH_TURNOVER
    elif FailureMode.PROD_CORRELATION in modes:
        primary = FailureMode.PROD_CORRELATION
    elif FailureMode.LOW_SUB_UNIVERSE_SHARPE in modes:
        primary = FailureMode.LOW_SUB_UNIVERSE_SHARPE
    elif FailureMode.MARGINAL_SHARPE in modes:
        primary = FailureMode.MARGINAL_SHARPE
    elif modes:
        primary = modes[0]
    else:
        primary = FailureMode.UNSPECIFIED

    return FailureDiagnosis(
        alpha_id=alpha_id,
        expression=expr,
        primary_cause=primary,
        all_modes=modes,
        metrics={
            "sharpe": sharpe,
            "fitness": fitness,
            "turnover": turnover,
            "pc_value": pc,
        },
        repair_recommendations=recs,
    )
