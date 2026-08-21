"""信号正交残差化与施密特投影模块 (Gram-Schmidt Orthogonalization).

功能:
  1. 矩阵级施密特正交化 (Gram-Schmidt):
     - 将新候选 Alpha 截面信号投影至已提交存量 Alpha 基底空间上
     - 剥离所有线性共线性成分，产出与存量库相关性为 0 的纯正交残差信号
  2. 表达式级正交残差重构:
     - 自动估算投影回归系数 beta，并将表达式合成为无相关残差公式 (x - beta * y)
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
import numpy as np

from alpha_operator_framework.domain.ast import to_canonical_string


def _matrix_inner_product(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个截面矩阵在有效非空时空点上的内积 (Frobenius Inner Product)."""
    valid = ~np.isnan(a) & ~np.isnan(b)
    if not np.any(valid):
        return 0.0
    return float(np.sum(a[valid] * b[valid]))


def compute_projection_beta(candidate: np.ndarray, base: np.ndarray) -> float:
    """计算候选信号在基底信号上的正交投影回归系数 beta.

    beta = <candidate, base> / <base, base>
    """
    denom = _matrix_inner_product(base, base)
    if denom <= 1e-10:
        return 0.0
    numer = _matrix_inner_product(candidate, base)
    return float(numer / denom)


def gram_schmidt_residualize(
    candidate_matrix: np.ndarray,
    basis_matrices: Sequence[np.ndarray],
) -> np.ndarray:
    """对候选 Alpha 矩阵执行 Gram-Schmidt 正交残差化.

    逐个剥离存量基底矩阵的投影成分:
      residual = candidate - sum_k ( beta_k * basis_k )

    Args:
        candidate_matrix: 形状为 (T, N) 的候选因子矩阵
        basis_matrices: 存量基底因子矩阵列表 (每个形状为 (T, N))

    Returns:
        与所有 basis_matrices 完全正交的残差因子矩阵 (T, N)
    """
    residual = candidate_matrix.copy()

    for base in basis_matrices:
        if base is None or base.shape != candidate_matrix.shape:
            continue
        beta = compute_projection_beta(residual, base)
        if abs(beta) > 1e-6:
            residual = residual - beta * base

    return residual


def build_orthogonal_expression(
    candidate_expr: str,
    base_expr: str,
    beta: float = 1.0,
) -> str:
    """将候选表达式与基底表达式合成为正交残差表达式字符串."""
    try:
        raw = f"({candidate_expr}) - ({beta:.4f} * ({base_expr}))"
        return to_canonical_string(raw)
    except Exception:
        return f"({candidate_expr}) - ({beta:.4f} * ({base_expr}))"
