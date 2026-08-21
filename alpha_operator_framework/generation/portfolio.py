"""Super-Alpha 2.0 投资组合优化与风险平价合成器 (Portfolio Optimization & Super-Alpha 2.0).

理论支撑:
  1. Marcos López de Prado (2016) "Building Diversified Portfolios that Outperform Out-of-Sample" (Hierarchical Risk Parity, HRP)
  2. 逆波动率平价与收缩协方差组合加权

功能:
  1. compute_inverse_volatility_weights: 逆波动率风险平价加权
  2. compute_hrp_weights: 分层风险平价 (HRP) 最优权重分配 (无需矩阵求逆，天然抗奇异/高相关)
  3. build_super_alpha_2: 自动化合成具备最优风险收益比的 Super-Alpha 2.0 组合公式
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from alpha_operator_framework.domain.ast import to_canonical_string


class PortfolioMethod(str, Enum):
    """组合权重优化算法."""

    EQUAL_WEIGHT = "equal_weight"
    INVERSE_VOLATILITY = "inverse_volatility"
    HRP = "hrp"


@dataclass
class SuperAlpha2Composite:
    """Super-Alpha 2.0 组合合成结果."""

    composite_expression: str
    weights: Dict[str, float]
    method: str
    expected_sharpe: float
    portfolio_turnover: float


def compute_inverse_volatility_weights(returns_matrix: np.ndarray) -> np.ndarray:
    """计算逆波动率权重 (Inverse Volatility Weights).

    w_i = (1 / sigma_i) / sum_j (1 / sigma_j)
    """
    T, M = returns_matrix.shape
    if M <= 1:
        return np.ones(M, dtype=float)

    vols = np.nanstd(returns_matrix, axis=0)
    vols = np.where(vols <= 1e-8, 1e-8, vols)

    inv_vols = 1.0 / vols
    weights = inv_vols / np.sum(inv_vols)
    return weights


def _single_linkage_numpy(dist: np.ndarray) -> np.ndarray:
    """纯 NumPy 实现单链接分层聚类 (Single Linkage)，零第三方库依赖.

    返回形状为 (M-1, 4) 的 linkage 矩阵: [cluster_a, cluster_b, distance, cluster_size]
    """
    M = dist.shape[0]
    clusters = {i: [i] for i in range(M)}
    current_dist = dist.copy()
    np.fill_diagonal(current_dist, np.inf)

    linkage_rows: List[List[float]] = []
    active_indices = list(range(M))

    for step in range(M - 1):
        # 寻找距离最近的两个簇
        min_idx = np.argmin(current_dist)
        i_local, j_local = np.unravel_index(min_idx, current_dist.shape)
        if i_local > j_local:
            i_local, j_local = j_local, i_local

        c_i = active_indices[i_local]
        c_j = active_indices[j_local]
        min_d = float(current_dist[i_local, j_local])

        new_cluster_id = M + step
        size_new = len(clusters[c_i]) + len(clusters[c_j])
        clusters[new_cluster_id] = clusters[c_i] + clusters[c_j]

        linkage_rows.append([float(c_i), float(c_j), min_d, float(size_new)])

        # 计算新簇与其余簇的单链接距离 min(d_i, d_j)
        new_dists = np.minimum(current_dist[i_local, :], current_dist[j_local, :])

        # 删除旧簇，添加新簇
        current_dist = np.delete(current_dist, [i_local, j_local], axis=0)
        current_dist = np.delete(current_dist, [i_local, j_local], axis=1)
        new_dists = np.delete(new_dists, [i_local, j_local])

        active_indices.pop(j_local)
        active_indices.pop(i_local)

        # 扩展矩阵
        k = len(active_indices)
        expanded = np.zeros((k + 1, k + 1), dtype=float)
        expanded[:k, :k] = current_dist
        expanded[:k, k] = new_dists
        expanded[k, :k] = new_dists
        expanded[k, k] = np.inf

        current_dist = expanded
        active_indices.append(new_cluster_id)

    return np.array(linkage_rows, dtype=float)


def _get_quasi_diag(linkage_matrix: np.ndarray) -> List[int]:
    """根据层次聚类 linkage 矩阵重构叶子节点的拟对角化排序 (Quasi-Diagonalization)."""
    root = int(linkage_matrix[-1, 0]), int(linkage_matrix[-1, 1])
    n = len(linkage_matrix) + 1

    order = [root[0], root[1]]
    while max(order) >= n:
        new_order = []
        for item in order:
            if item >= n:
                cluster_idx = item - n
                new_order.append(int(linkage_matrix[cluster_idx, 0]))
                new_order.append(int(linkage_matrix[cluster_idx, 1]))
            else:
                new_order.append(item)
        order = new_order
    return order


def _compute_cluster_var(cov: np.ndarray, cluster_items: List[int]) -> float:
    """计算子簇在逆方差分配下的组合方差."""
    sub_cov = cov[np.ix_(cluster_items, cluster_items)]
    diag_inv = 1.0 / np.diag(sub_cov)
    w = diag_inv / np.sum(diag_inv)
    return float(np.dot(w.T, np.dot(sub_cov, w)))


def compute_hrp_weights(returns_matrix: np.ndarray) -> np.ndarray:
    """分层风险平价算法 (Hierarchical Risk Parity, HRP).

    分步执行:
      1. 相关性距离树与层次聚类
      2. 拟对角化矩阵重排 (Quasi-Diagonalization)
      3. 递归二分二叉树方差倒数权重分配 (Recursive Bisection)

    无需计算协方差矩阵的逆 (Covariance Inverse)，完全避免矩阵病态条件数与奇异性崩塌。
    """
    T, M = returns_matrix.shape
    if M <= 1:
        return np.ones(M, dtype=float)
    if M == 2:
        return compute_inverse_volatility_weights(returns_matrix)

    # 1. 协方差与相关性矩阵
    cov = np.cov(returns_matrix, rowvar=False)
    vols = np.sqrt(np.diag(cov)) + 1e-8
    corr = cov / np.outer(vols, vols)
    corr = np.clip(corr, -1.0, 1.0)

    # 2. 距离矩阵: D_i,j = sqrt(0.5 * (1 - rho_i,j))
    dist = np.sqrt(0.5 * (1.0 - corr))
    np.fill_diagonal(dist, 0.0)

    # 3. 凝聚层次聚类 (Single Linkage)
    link = _single_linkage_numpy(dist)

    # 4. 拟对角化重排
    sort_order = _get_quasi_diag(link)

    # 5. 递归二分权重分配
    weights = np.ones(M, dtype=float)
    clustered_alphas = [sort_order]

    while clustered_alphas:
        new_clusters = []
        for cluster in clustered_alphas:
            if len(cluster) > 1:
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                var_left = _compute_cluster_var(cov, left)
                var_right = _compute_cluster_var(cov, right)

                # 分配因子 alpha = 1 - var_left / (var_left + var_right)
                denom = var_left + var_right
                alloc_left = 1.0 - (var_left / denom) if denom > 1e-8 else 0.5
                alloc_right = 1.0 - alloc_left

                for idx in left:
                    weights[idx] *= alloc_left
                for idx in right:
                    weights[idx] *= alloc_right

                new_clusters.append(left)
                new_clusters.append(right)
        clustered_alphas = new_clusters

    # 归一化
    weights = weights / np.sum(weights)
    return weights


def build_super_alpha_2(
    alphas: Sequence[Dict[str, Any]],
    returns_matrix: np.ndarray,
    method: PortfolioMethod = PortfolioMethod.HRP,
) -> SuperAlpha2Composite:
    """根据候选 Alpha 清单与收益矩阵，生成最优风险收益比的 Super-Alpha 2.0 公式."""
    M = len(alphas)
    if M == 0:
        raise ValueError("alphas sequence cannot be empty")

    if method == PortfolioMethod.HRP:
        try:
            raw_weights = compute_hrp_weights(returns_matrix)
        except Exception:
            raw_weights = compute_inverse_volatility_weights(returns_matrix)
    elif method == PortfolioMethod.INVERSE_VOLATILITY:
        raw_weights = compute_inverse_volatility_weights(returns_matrix)
    else:
        raw_weights = np.ones(M, dtype=float) / float(M)

    # 过滤微小权重 (阈值 < 1%)
    weights_dict: Dict[str, float] = {}
    terms: List[str] = []

    for i, a in enumerate(alphas):
        w = float(raw_weights[i])
        expr = a.get("expression") or a.get("regular") or ""
        aid = a.get("alpha_id") or a.get("id") or f"a_{i}"
        if w >= 0.01 and expr:
            weights_dict[aid] = round(w, 4)
            terms.append(f"{w:.4f} * ({expr})")

    # 组合表达式
    composite_raw = " + ".join(terms)
    try:
        can_composite = to_canonical_string(composite_raw)
    except Exception:
        can_composite = composite_raw

    # 计算预期组合夏普
    port_ret = np.dot(returns_matrix, raw_weights)
    mean_r = float(np.nanmean(port_ret))
    std_r = float(np.nanstd(port_ret)) + 1e-8
    expected_sharpe = float(mean_r / std_r * np.sqrt(252))

    # 计算预期换手率
    avg_turnover = float(np.mean([float(a.get("turnover", 0.20)) for a in alphas])) * 0.7  # 多因子对冲分散降换手

    return SuperAlpha2Composite(
        composite_expression=can_composite,
        weights=weights_dict,
        method=method.value,
        expected_sharpe=round(expected_sharpe, 2),
        portfolio_turnover=round(avg_turnover, 2),
    )
