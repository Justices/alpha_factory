"""统计防过拟合与多重检验校正体系 (Statistical Overfitting Defense).

理论支撑:
  1. Marcos López de Prado (2014) "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality"
  2. David H. Bailey et al. (2014) "The Probability of Backtest Overfitting (PBO)"
  3. Campbell R. Harvey, Yan Liu, Heqing Zhu (2016) "... and the Cross-Section of Expected Returns" (Haircut Sharpe)

功能:
  - compute_psr: 计算概率夏普比率 (Probabilistic Sharpe Ratio)
  - compute_expected_max_sharpe: 计算在零真实技能纯随机搜索下的期望最大夏普 E[max_N]
  - compute_dsr: 计算折损夏普比率 (Deflated Sharpe Ratio)
  - compute_haircut_sharpe: 多重检验保守打折夏普
  - compute_pbo_cscv: 组合对称交叉验证 (CSCV) 计算过拟合概率 PBO
"""

from __future__ import annotations

import itertools
import math
from typing import Any, List, Optional, Sequence, Tuple
import numpy as np


def _norm_cdf(x: float) -> float:
    """标准正态分布累积概率函数 (CDF)."""
    return 0.5 * (1.0 + math.erf(float(x) / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数函数 (Inverse CDF / Quantile) — 基于 Acklam 有理逼近算法."""
    p = float(p)
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0

    a = (
        -3.969683028665376e+01,  2.209460984245205e+02,
        -2.759285104469687e+02,  1.383577518672690e+02,
        -3.066479806614716e+01,  2.506628277459239e+00,
    )
    b = (
        -5.447609879822406e+01,  1.615858368580409e+02,
        -1.556989798598866e+02,  6.680133369964407e+01,
        -1.328068155288572e+01,
    )
    c = (
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00,  2.938163982698783e+00,
    )
    d = (
         7.784695709041462e-03,  3.224671290700398e-01,
         2.445134137142996e+00,  3.754408661907416e+00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def compute_psr(
    sharpe: float,
    t_days: int,
    skew: float = 0.0,
    kurt: float = 3.0,
    benchmark_sharpe: float = 0.0,
) -> float:
    """计算概率夏普比率 (Probabilistic Sharpe Ratio, PSR).

    量化样本内测出的 Sharpe 真正大于 benchmark_sharpe 的统计置信概率 (0 ~ 1.0)。
    校正非正态收益分布（偏度 skew 与峰度 kurtosis）。

    公式:
      PSR(SR*) = Phi( (SR - SR*) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1) / 4 * SR^2) )
    """
    if t_days <= 1:
        return 0.5

    sr = float(sharpe)
    sr_star = float(benchmark_sharpe)
    t = float(t_days)

    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr ** 2)
    if denom_sq <= 1e-8:
        denom_sq = 1e-8

    std_err = math.sqrt(denom_sq)
    z_stat = (sr - sr_star) * math.sqrt(t - 1.0) / std_err

    # 标准正态累积分布函数 Phi
    psr = _norm_cdf(z_stat)
    return max(0.0, min(1.0, psr))


def compute_expected_max_sharpe(
    trial_count: int,
    sharpe_std: float = 0.5,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """计算在零超额收益 (Null Hypothesis) 下，尝试 trial_count 次由于随机抽样产生的期望最大夏普比率 E[max_N].

    极值理论推导 (Extreme Value Theory Approximation):
      E[max_N] ≈ sigma_SR * ( (1 - gamma) * Z^(-1)(1 - 1/N) + gamma * Z^(-1)(1 - 1/(N * e)) )
      其中 gamma ≈ 0.5772156649 (欧拉-马歇罗尼常数), e ≈ 2.7182818284
    """
    n = max(1, int(trial_count))
    if n == 1:
        return 0.0

    gamma = 0.57721566490153286  # Euler-Mascheroni constant
    e = math.e
    sigma = max(1e-4, float(sharpe_std))

    # 分位数计算
    q1 = 1.0 - 1.0 / n
    q2 = 1.0 - 1.0 / (n * e)

    # 边界保护
    q1 = min(0.9999999999, max(0.5, q1))
    q2 = min(0.9999999999, max(0.5, q2))

    z1 = _norm_ppf(q1)
    z2 = _norm_ppf(q2)

    expected_max = sigma * ((1.0 - gamma) * z1 + gamma * z2)
    return float(max(0.0, expected_max))


def compute_dsr(
    sharpe: float,
    trial_count: int,
    sharpe_std: float = 0.5,
    t_days: int = 252,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """计算折损夏普比率 (Deflated Sharpe Ratio, DSR).

    在评估因子的 Sharpe 时，将整个研发过程中尝试的总次数 (trial_count) 纳入考量。
    只有当 DSR > 0.95 (即在 5% 显著性水平下超过纯随机试错产生的最大夏普) 时，
    该因子才具有真正的统计显著性，而非数据挖掘产生的假阳性。

    Returns:
        DSR 置信概率 (0.0 ~ 1.0)，通常 >= 0.95 判定为真正有效
    """
    sr = float(sharpe)
    if sr <= 0 or trial_count <= 1:
        return compute_psr(sr, t_days, skew=skew, kurt=kurt, benchmark_sharpe=0.0)

    # 1. 计算试错次数下的期望最大假夏普
    e_max_sr = compute_expected_max_sharpe(
        trial_count=trial_count,
        sharpe_std=sharpe_std,
        skew=skew,
        kurt=kurt,
    )

    # 2. 将基准设为 E[max_N] 计算 PSR
    return compute_psr(
        sharpe=sr,
        t_days=t_days,
        skew=skew,
        kurt=kurt,
        benchmark_sharpe=e_max_sr,
    )


def compute_haircut_sharpe(
    sharpe: float,
    trial_count: int,
    t_days: int = 252,
) -> float:
    """计算基于 Harvey-Liu-Zhu 多重假设检验的打折保守夏普 (Haircut Sharpe).

    公式:
      SR_haircut = SR * sqrt( max(0, 1 - 2 * ln(N) / T) )
    """
    sr = float(sharpe)
    if sr <= 0 or trial_count <= 1:
        return sr

    n = float(trial_count)
    t = float(max(10, t_days))

    discount_sq = 1.0 - (2.0 * math.log(n)) / t
    if discount_sq <= 0:
        return 0.0

    return float(sr * math.sqrt(discount_sq))


def compute_pbo_cscv(
    returns_matrix: np.ndarray,
    n_partitions: int = 8,
) -> float:
    """使用组合对称交叉验证 (CSCV) 计算过拟合概率 (Probability of Backtest Overfitting, PBO).

    Args:
        returns_matrix: 形状为 (T, M) 的各候选因子日度收益率矩阵 (T 为时间步, M 为候选因子数量)
        n_partitions: 时间序列切分的块数 S (必须为偶数，如 8 或 16)

    Returns:
        PBO 值 (0.0 ~ 1.0): 样本内 (IS) 表现最优的因子在样本外 (OOS) 排名落入中位数以下的概率。
        PBO < 0.30 判定为低过拟合风险；PBO > 0.50 判定为严重过拟合。
    """
    T, M = returns_matrix.shape
    if M <= 1 or T < n_partitions or n_partitions % 2 != 0:
        return 0.0

    # 将 T 切分为 S 个块
    block_size = T // n_partitions
    blocks = [returns_matrix[i * block_size : (i + 1) * block_size] for i in range(n_partitions)]

    # 构造组合 C(S, S/2)
    s_half = n_partitions // 2
    combos = list(itertools.combinations(range(n_partitions), s_half))

    overfit_count = 0
    total_combos = len(combos)

    for is_indices in combos:
        oos_indices = [i for i in range(n_partitions) if i not in is_indices]

        # 拼接 IS 和 OOS 收益序列
        is_ret = np.vstack([blocks[i] for i in is_indices])
        oos_ret = np.vstack([blocks[i] for i in oos_indices])

        # 计算各因子在 IS 上的年化 Sharpe
        is_mean = np.nanmean(is_ret, axis=0)
        is_std = np.nanstd(is_ret, axis=0) + 1e-8
        is_sharpes = is_mean / is_std * np.sqrt(252)

        # 找出 IS 表现最好的因子序号
        best_is_idx = int(np.argmax(is_sharpes))

        # 计算所有因子在 OOS 上的年化 Sharpe
        oos_mean = np.nanmean(oos_ret, axis=0)
        oos_std = np.nanstd(oos_ret, axis=0) + 1e-8
        oos_sharpes = oos_mean / oos_std * np.sqrt(252)

        # 计算 best_is_idx 在 OOS 中的相对百分位排名 (0.0 ~ 1.0)
        best_oos_score = oos_sharpes[best_is_idx]
        rank_oos = np.sum(oos_sharpes <= best_oos_score) / float(M)

        # 若在 OOS 上的排名低于中位数 (0.5)，则视为过拟合事件
        if rank_oos < 0.5:
            overfit_count += 1

    return float(overfit_count / total_combos)


from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrialRecord:
    """单个试验记录 (不可变事实)."""
    trial_id: str
    expression: str
    family: str
    region: str
    universe: str
    created_at: str
    metrics: dict = field(default_factory=dict)


class TrialLedger:
    """真实试验自由度账本 (Trial Ledger) — 记录全生命周期搜索空间与有效试验次数."""

    def __init__(self):
        self._trials_by_family: dict[str, int] = {}
        self._total_trials: int = 0
        self._records: list[TrialRecord] = []

    def record_trial(
        self,
        expression: str,
        family: str = "default",
        region: str = "GBR",
        universe: str = "TOP700",
        metrics: Optional[dict] = None,
    ) -> TrialRecord:
        """记录一次真实试验，累加有效试验自由度."""
        self._total_trials += 1
        self._trials_by_family[family] = self._trials_by_family.get(family, 0) + 1
        rec = TrialRecord(
            trial_id=f"TRIAL_{self._total_trials:06d}",
            expression=expression,
            family=family,
            region=region,
            universe=universe,
            created_at=datetime.now().isoformat(),
            metrics=metrics or {},
        )
        self._records.append(rec)
        return rec

    def get_effective_trials(self, family: Optional[str] = None) -> int:
        """获取真实的有效试验次数 N."""
        if family and family in self._trials_by_family:
            return max(1, self._trials_by_family[family])
        return max(1, self._total_trials)

    @staticmethod
    def compute_distribution_moments(
        returns_series: Optional[Sequence[float]] = None,
    ) -> Tuple[float, float]:
        """从真实收益序列计算偏度 (skewness) 与超额峰度 (kurtosis)."""
        if returns_series is None or len(returns_series) < 10:
            return 0.0, 3.0
        arr = np.asarray(returns_series, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) < 10 or np.std(arr) == 0:
            return 0.0, 3.0
        mean = float(np.mean(arr))
        std = float(np.std(arr))
        if std == 0:
            return 0.0, 3.0
        normed = (arr - mean) / std
        skew = float(np.mean(normed ** 3))
        kurt = float(np.mean(normed ** 4))
        return skew, kurt

