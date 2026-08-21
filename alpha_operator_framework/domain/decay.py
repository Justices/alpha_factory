"""因子衰减半衰期探测器 (Alpha Decay Profiler).

功能:
  1. 计算因子信号与未来多期收益率的前向截面 Rank IC 衰减曲线 (Forward IC Decay Curve, tau in [1, 20])
  2. 基于指数衰减模型 IC(tau) = IC0 * exp(-lambda * tau) 精确拟合因子半衰期 (Half-Life, t_1/2)
  3. 自动推荐最优衰减平滑参数 (recommended_decay)，告别经验硬编码
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from alpha_operator_framework.domain.sandbox.ops import cs_rank


class DecaySpeed(str, Enum):
    """因子衰减速度分级."""

    ULTRA_FAST = "ultra_fast"   # 超快衰减 (半衰期 <= 2 天, 如高频订单流/短期均值回归)
    FAST = "fast"               # 快速衰减 (2 < 半衰期 <= 5 天, 如量价反转)
    MODERATE = "moderate"       # 中速衰减 (5 < 半衰期 <= 12 天, 如分析师修正/短期动量)
    PERSISTENT = "persistent"   # 慢速稳健 (12 < 半衰期 <= 25 天, 如基本面盈余质量/成长动量)
    SLOW = "slow"               # 超长生命周期 (半衰期 > 25 天, 如价值/低估值/资产负债结构)


@dataclass
class AlphaDecayProfile:
    """因子衰减特征画像."""

    ic_curve: List[float]               # 各前向滞后期 (tau=1..max_lag) 的 Rank IC 列表
    initial_ic: float                   # 1 期前向 Rank IC
    half_life: float                    # 拟合得出的经验半衰期 (交易日数)
    recommended_decay: int              # 自动推荐的 decay 参数 (整数)
    decay_speed: DecaySpeed             # 衰减速度评级
    lambda_decay: float                 # 指数衰减率系数 lambda

    @property
    def is_tradable(self) -> bool:
        """是否具有可交易的初始信号强度."""
        return abs(self.initial_ic) >= 0.008


def _calc_rank_ic(signal: np.ndarray, returns: np.ndarray) -> float:
    """计算单个截面时点的 Rank IC."""
    valid_mask = ~np.isnan(signal) & ~np.isnan(returns)
    if np.sum(valid_mask) < 5:
        return 0.0

    s = signal[valid_mask]
    r = returns[valid_mask]

    # 截面秩转换
    s_rank = np.argsort(np.argsort(s)).astype(float)
    r_rank = np.argsort(np.argsort(r)).astype(float)

    # 计算相关系数
    s_diff = s_rank - np.mean(s_rank)
    r_diff = r_rank - np.mean(r_rank)

    denom = np.sqrt(np.sum(s_diff ** 2) * np.sum(r_diff ** 2))
    if denom <= 1e-8:
        return 0.0
    return float(np.sum(s_diff * r_diff) / denom)


def profile_alpha_decay(
    signal_matrix: np.ndarray,
    returns_matrix: np.ndarray,
    max_lag: int = 20,
) -> AlphaDecayProfile:
    """根据因子截面信号矩阵与日收益率矩阵，拟合前向 IC 衰减曲线与半衰期.

    Args:
        signal_matrix: 形状为 (T, N) 的截面因子信号矩阵
        returns_matrix: 形状为 (T, N) 的日收益率矩阵 (与 signal 同维度)
        max_lag: 最大前向考察天数 (默认 20 个交易日)

    Returns:
        AlphaDecayProfile 画像结果
    """
    T, N = signal_matrix.shape
    max_lag = min(max_lag, T - 10)

    ic_curve: List[float] = []

    # 1. 逐期计算前向 lag 的平均 Rank IC
    for lag in range(1, max_lag + 1):
        daily_ics: List[float] = []
        for t in range(T - lag):
            sig_t = signal_matrix[t]
            ret_t_lag = returns_matrix[t + lag]
            ic = _calc_rank_ic(sig_t, ret_t_lag)
            if not np.isnan(ic):
                daily_ics.append(ic)

        mean_ic = float(np.mean(daily_ics)) if daily_ics else 0.0
        ic_curve.append(mean_ic)

    initial_ic = ic_curve[0] if ic_curve else 0.0
    abs_initial_ic = abs(initial_ic)

    # 2. 如果初始 IC 极微弱，返回默认画像
    if abs_initial_ic < 1e-4:
        return AlphaDecayProfile(
            ic_curve=ic_curve,
            initial_ic=initial_ic,
            half_life=5.0,
            recommended_decay=5,
            decay_speed=DecaySpeed.MODERATE,
            lambda_decay=0.1386,
        )

    # 3. 拟合指数衰减曲线: abs(IC(tau)) = abs(IC_0) * exp(-lambda * (tau - 1))
    # 取对数线性回归: ln(abs(IC) / abs(IC_0)) = -lambda * (tau - 1)
    x_vals: List[float] = []
    y_vals: List[float] = []

    sign_initial = np.sign(initial_ic)

    for tau_idx, ic_val in enumerate(ic_curve):
        tau = tau_idx + 1
        # 仅保留同号衰减点
        if ic_val * sign_initial > 0:
            ratio = max(1e-4, min(1.0, abs(ic_val) / abs_initial_ic))
            x_vals.append(float(tau - 1))
            y_vals.append(math.log(ratio))

    if len(x_vals) >= 2:
        x_arr = np.array(x_vals)
        y_arr = np.array(y_vals)
        # OLS 斜率 (过原点): -lambda = sum(x * y) / sum(x^2)
        denom = np.sum(x_arr ** 2)
        if denom > 1e-6:
            slope = np.sum(x_arr * y_arr) / denom
            lambda_decay = max(0.01, min(2.0, -slope))
        else:
            lambda_decay = 0.14
    else:
        lambda_decay = 0.14

    # 4. 计算半衰期: t_1/2 = ln(2) / lambda
    half_life = math.log(2.0) / lambda_decay

    # 5. 确定衰减速度与推荐 decay 参数
    if half_life <= 2.0:
        speed = DecaySpeed.ULTRA_FAST
        recommended_decay = max(1, min(3, round(half_life * 1.5)))
    elif half_life <= 5.0:
        speed = DecaySpeed.FAST
        recommended_decay = max(3, min(6, round(half_life * 1.5)))
    elif half_life <= 12.0:
        speed = DecaySpeed.MODERATE
        recommended_decay = max(6, min(15, round(half_life * 1.2)))
    elif half_life <= 25.0:
        speed = DecaySpeed.PERSISTENT
        recommended_decay = max(15, min(25, round(half_life * 1.0)))
    else:
        speed = DecaySpeed.SLOW
        recommended_decay = 30

    return AlphaDecayProfile(
        ic_curve=ic_curve,
        initial_ic=initial_ic,
        half_life=float(round(half_life, 2)),
        recommended_decay=int(recommended_decay),
        decay_speed=speed,
        lambda_decay=float(round(lambda_decay, 4)),
    )
