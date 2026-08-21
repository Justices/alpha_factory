"""NumPy 向量化 Alpha 算子库 — 本地沙盒核心计算层.

所有算子输入均为 2D NumPy 矩阵 X (Shape: [T, N]，T 为时间步，N 为资产标的数)。
具备完整的 NaN 容错与无界/除零保护。
"""

from __future__ import annotations

import numpy as np
from typing import Any, Dict, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# 基础截面算子 (Cross-Sectional Operators, Axis=1)
# ---------------------------------------------------------------------------

def cs_rank(X: np.ndarray) -> np.ndarray:
    """截面百分比排序 (按行排序，归一化到 [0, 1])."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    for t in range(X.shape[0]):
        row = X[t]
        valid_mask = ~np.isnan(row)
        n_valid = np.sum(valid_mask)
        if n_valid > 1:
            valid_vals = row[valid_mask]
            # argsort 实现 rank
            ranks = np.empty(n_valid, dtype=np.float64)
            order = valid_vals.argsort()
            ranks[order] = np.arange(1, n_valid + 1, dtype=np.float64)
            out[t, valid_mask] = (ranks - 1.0) / (n_valid - 1.0)
        elif n_valid == 1:
            out[t, valid_mask] = 0.5
    return out


def cs_zscore(X: np.ndarray) -> np.ndarray:
    """截面标准化 (X - mean) / std."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    for t in range(X.shape[0]):
        row = X[t]
        valid_mask = ~np.isnan(row)
        if np.sum(valid_mask) > 1:
            valid_vals = row[valid_mask]
            mean = np.mean(valid_vals)
            std = np.std(valid_vals)
            if std > 1e-8:
                out[t, valid_mask] = (valid_vals - mean) / std
            else:
                out[t, valid_mask] = 0.0
    return out


def cs_scale(X: np.ndarray, a: float = 1.0) -> np.ndarray:
    """截面缩放 X / sum(|X|) * a."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    for t in range(X.shape[0]):
        row = X[t]
        valid_mask = ~np.isnan(row)
        if np.sum(valid_mask) > 0:
            valid_vals = row[valid_mask]
            sum_abs = np.sum(np.abs(valid_vals))
            if sum_abs > 1e-8:
                out[t, valid_mask] = valid_vals / sum_abs * float(a)
            else:
                out[t, valid_mask] = 0.0
    return out


def cs_quantile(X: np.ndarray) -> np.ndarray:
    """截面分位数 (等价于 cs_rank)."""
    return cs_rank(X)


def cs_reverse(X: np.ndarray) -> np.ndarray:
    """截面反向 -X."""
    return -X


def cs_inverse(X: np.ndarray) -> np.ndarray:
    """倒数 1 / X (避开 0)."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    mask = ~np.isnan(X) & (np.abs(X) > 1e-8)
    out[mask] = 1.0 / X[mask]
    return out


# ---------------------------------------------------------------------------
# 时间序列算子 (Time-Series Operators, Axis=0)
# ---------------------------------------------------------------------------

def ts_delay(X: np.ndarray, w: int) -> np.ndarray:
    """滞后算子 lag(X, w)."""
    w = int(w)
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0:
        return X.copy()
    if w < X.shape[0]:
        out[w:] = X[:-w]
    return out


def ts_delta(X: np.ndarray, w: int) -> np.ndarray:
    """时序差分 X[t] - X[t-w]."""
    w = int(w)
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0:
        return np.zeros_like(X)
    if w < X.shape[0]:
        out[w:] = X[w:] - X[:-w]
    return out


def ts_mean(X: np.ndarray, w: int) -> np.ndarray:
    """滚动均值."""
    w = int(w)
    T, N = X.shape
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0 or w > T:
        return out

    # 利用 cumsum 快速向量化计算滚动均值
    # nan 处理：前推填充或掩码
    for i in range(w - 1, T):
        window = X[i - w + 1 : i + 1]
        out[i] = np.nanmean(window, axis=0)
    return out


def ts_sum(X: np.ndarray, w: int) -> np.ndarray:
    """滚动求和."""
    w = int(w)
    T, N = X.shape
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0 or w > T:
        return out
    for i in range(w - 1, T):
        window = X[i - w + 1 : i + 1]
        out[i] = np.nansum(window, axis=0)
    return out


def ts_std_dev(X: np.ndarray, w: int) -> np.ndarray:
    """滚动标准差."""
    w = int(w)
    T, N = X.shape
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 1 or w > T:
        return out
    for i in range(w - 1, T):
        window = X[i - w + 1 : i + 1]
        out[i] = np.nanstd(window, axis=0)
    return out


def ts_rank(X: np.ndarray, w: int) -> np.ndarray:
    """滚动时序百分比排序 (当前值在过去 w 天内的相对排名 [0, 1])."""
    w = int(w)
    T, N = X.shape
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0 or w > T:
        return out

    for i in range(w - 1, T):
        window = X[i - w + 1 : i + 1]  # shape: (w, N)
        curr = X[i]                     # shape: (N,)
        # 计算过去 w 天中小于等于当前值的数量
        valid_cnt = np.sum(~np.isnan(window), axis=0)
        less_cnt = np.sum(window <= curr[None, :], axis=0)

        valid_mask = valid_cnt > 1
        out[i, valid_mask] = (less_cnt[valid_mask] - 1.0) / (valid_cnt[valid_mask] - 1.0)
        single_mask = valid_cnt == 1
        out[i, single_mask] = 0.5
    return out


def ts_decay_linear(X: np.ndarray, w: int) -> np.ndarray:
    """线性加权时序衰减 (权重 1, 2, ..., w)."""
    w = int(w)
    T, N = X.shape
    out = np.full_like(X, np.nan, dtype=np.float64)
    if w <= 0 or w > T:
        return out

    weights = np.arange(1, w + 1, dtype=np.float64)
    weights_sum = np.sum(weights)

    for i in range(w - 1, T):
        window = X[i - w + 1 : i + 1]  # (w, N)
        # 加权平均
        w_expanded = weights[:, None]
        valid_mask = ~np.isnan(window)
        weighted_vals = np.where(valid_mask, window * w_expanded, 0.0)
        weighted_w = np.where(valid_mask, w_expanded, 0.0)
        sum_w = np.sum(weighted_w, axis=0)

        valid_col = sum_w > 0
        out[i, valid_col] = np.sum(weighted_vals[:, valid_col], axis=0) / sum_w[valid_col]
    return out


def ts_zscore(X: np.ndarray, w: int) -> np.ndarray:
    """滚动时序 Z-Score (X - ts_mean) / ts_std_dev."""
    w = int(w)
    mean = ts_mean(X, w)
    std = ts_std_dev(X, w)
    out = np.full_like(X, np.nan, dtype=np.float64)
    valid = ~np.isnan(mean) & ~np.isnan(std) & (std > 1e-8)
    out[valid] = (X[valid] - mean[valid]) / std[valid]
    return out


# ---------------------------------------------------------------------------
# 分组算子 (Group Operators)
# ---------------------------------------------------------------------------

def group_neutralize(X: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """按行业/分组中性化 (去行业均值)."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    T, N = X.shape

    # 兼容 1D 或 2D 组别矩阵
    is_2d_groups = (groups.ndim == 2)

    for t in range(T):
        row = X[t]
        grp = groups[t] if is_2d_groups else groups
        valid_mask = ~np.isnan(row) & ~np.isnan(grp)
        if np.sum(valid_mask) > 0:
            unique_grps = np.unique(grp[valid_mask])
            res_row = row.copy()
            for g in unique_grps:
                g_mask = valid_mask & (grp == g)
                if np.sum(g_mask) > 0:
                    g_mean = np.mean(row[g_mask])
                    res_row[g_mask] = row[g_mask] - g_mean
            out[t, valid_mask] = res_row[valid_mask]
    return out


def group_rank(X: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """分组百分比排序."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    T, N = X.shape
    is_2d_groups = (groups.ndim == 2)

    for t in range(T):
        row = X[t]
        grp = groups[t] if is_2d_groups else groups
        valid_mask = ~np.isnan(row) & ~np.isnan(grp)
        if np.sum(valid_mask) > 0:
            unique_grps = np.unique(grp[valid_mask])
            for g in unique_grps:
                g_mask = valid_mask & (grp == g)
                n_g = np.sum(g_mask)
                if n_g > 1:
                    vals = row[g_mask]
                    order = vals.argsort()
                    ranks = np.empty(n_g, dtype=np.float64)
                    ranks[order] = np.arange(1, n_g + 1, dtype=np.float64)
                    out[t, g_mask] = (ranks - 1.0) / (n_g - 1.0)
                elif n_g == 1:
                    out[t, g_mask] = 0.5
    return out


def group_zscore(X: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """分组 Z-Score."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    T, N = X.shape
    is_2d_groups = (groups.ndim == 2)

    for t in range(T):
        row = X[t]
        grp = groups[t] if is_2d_groups else groups
        valid_mask = ~np.isnan(row) & ~np.isnan(grp)
        if np.sum(valid_mask) > 0:
            unique_grps = np.unique(grp[valid_mask])
            for g in unique_grps:
                g_mask = valid_mask & (grp == g)
                if np.sum(g_mask) > 1:
                    vals = row[g_mask]
                    m = np.mean(vals)
                    s = np.std(vals)
                    if s > 1e-8:
                        out[t, g_mask] = (vals - m) / s
                    else:
                        out[t, g_mask] = 0.0
    return out


# ---------------------------------------------------------------------------
# 向量与通用数学算子 (Vector / Math Operators)
# ---------------------------------------------------------------------------

def signed_power(X: np.ndarray, p: float) -> np.ndarray:
    """保号幂次 sign(X) * |X|^p."""
    out = np.full_like(X, np.nan, dtype=np.float64)
    mask = ~np.isnan(X)
    out[mask] = np.sign(X[mask]) * (np.abs(X[mask]) ** float(p))
    return out


# 算子注册表映射
SANDBOX_OPS_MAP = {
    # 截面算子
    "rank": cs_rank,
    "zscore": cs_zscore,
    "scale": cs_scale,
    "quantile": cs_quantile,
    "reverse": cs_reverse,
    "inverse": cs_inverse,
    # 时序算子
    "ts_delay": ts_delay,
    "ts_delta": ts_delta,
    "ts_mean": ts_mean,
    "ts_sum": ts_sum,
    "ts_std_dev": ts_std_dev,
    "ts_rank": ts_rank,
    "ts_decay_linear": ts_decay_linear,
    "ts_zscore": ts_zscore,
    # 分组算子
    "group_neutralize": group_neutralize,
    "group_rank": group_rank,
    "group_zscore": group_zscore,
    # 扩展数学
    "signed_power": signed_power,
    "abs": np.abs,
    "log": np.log,
    "sign": np.sign,
    "sqrt": np.sqrt,
}
