"""Deflated Sharpe Ratio (DSR), Probabilistic Sharpe Ratio (PSR), and PBO / CSCV.

纯 Python / NumPy 原生实现，消除对外部 scipy 库的强依赖。

References:
- Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. Journal of Portfolio Management, 40(5), 94-107.
- Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. Notices of the AMS, 61(5), 458-471.
- López de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

# Euler-Mascheroni constant
_EULER_MASCHERONI = 0.57721566490153286060651209008240243104215933593992


def _norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数 Phi(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数函数 / 逆累积分布函数 (Peter Acklam 高精度有理近似算法)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0

    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def compute_expected_max_sharpe(
    trial_count: int,
    sharpe_std: float = 0.5,
) -> float:
    """计算 N 次独立回测试验在零夏普原假设下的期望最大夏普比率 E[max_N]."""
    if trial_count <= 1:
        return 0.0
    z1 = _norm_ppf(1.0 - 1.0 / trial_count)
    z2 = _norm_ppf(1.0 - 1.0 / (trial_count * math.e))
    e_max = (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
    return float(sharpe_std * e_max)


def compute_psr(
    sharpe: float,
    t_days: int = 504,
    benchmark_sharpe: float = 0.0,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """计算概率夏普比率 (Probabilistic Sharpe Ratio - PSR)."""
    if t_days <= 1:
        return 0.0
    # 年化 Sharpe 的估计方差调整
    sr_daily = sharpe / math.sqrt(252.0)
    var_estimator = 1.0 - skewness * sr_daily + ((kurtosis - 1.0) / 4.0) * (sr_daily ** 2)
    if var_estimator <= 0:
        return 1.0 if sharpe > benchmark_sharpe else 0.0
    
    # 统计量 Z = (SR - SR*) * sqrt(T/63) / sqrt(V)
    z_stat = (sharpe - benchmark_sharpe) * math.sqrt(max(1.0, float(t_days)) / 63.0) / math.sqrt(var_estimator)
    return float(_norm_cdf(z_stat))


def compute_dsr(
    sharpe: float,
    trial_count: int = 50,
    t_days: int = 504,
    sharpe_std: float = 0.5,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """计算紧缩夏普比率 (Deflated Sharpe Ratio - DSR)."""
    if trial_count <= 1:
        return compute_psr(sharpe=sharpe, t_days=t_days, benchmark_sharpe=0.0, skewness=skewness, kurtosis=kurtosis)
    e_max_sr = compute_expected_max_sharpe(trial_count=trial_count, sharpe_std=sharpe_std)
    return compute_psr(sharpe=sharpe, t_days=t_days, benchmark_sharpe=e_max_sr, skewness=skewness, kurtosis=kurtosis)


def compute_haircut_sharpe(
    sharpe: float,
    trial_count: int = 50,
    t_days: int = 504,
    sharpe_std: float = 0.5,
) -> float:
    """根据多重测试折损计算 Haircut Sharpe 比率."""
    if sharpe <= 0 or trial_count <= 1:
        return sharpe
    e_max = compute_expected_max_sharpe(trial_count=trial_count, sharpe_std=sharpe_std)
    haircut_pct = min(0.95, e_max / (sharpe + e_max))
    return float(max(0.01, sharpe * (1.0 - haircut_pct)))


def compute_pbo_cscv(
    returns_matrix: np.ndarray,
    n_partitions: int = 8,
    n_splits: Optional[int] = None,
    n_test_splits: int = 2,
) -> float:
    """组合净化交叉验证 (CPCV) 计算回测过拟合概率 (PBO)."""
    t_len, n_strats = returns_matrix.shape
    splits = n_splits or n_partitions
    if n_strats < 2 or t_len < splits * 5:
        return 0.5

    block_size = t_len // splits
    blocks = [list(range(i * block_size, (i + 1) * block_size)) for i in range(splits)]
    if t_len > splits * block_size:
        blocks[-1].extend(range(splits * block_size, t_len))

    combos = list(itertools.combinations(range(splits), n_test_splits))
    if not combos:
        return 0.5

    underperform_count = 0

    for test_idx in combos:
        test_indices = []
        for ti in test_idx:
            test_indices.extend(blocks[ti])
        train_indices = [idx for idx in range(t_len) if idx not in test_indices]

        train_ret = returns_matrix[train_indices, :]
        test_ret = returns_matrix[test_indices, :]

        is_std = np.std(train_ret, axis=0) + 1e-12
        is_sharpes = (np.mean(train_ret, axis=0) / is_std) * math.sqrt(252.0)

        oos_std = np.std(test_ret, axis=0) + 1e-12
        oos_sharpes = (np.mean(test_ret, axis=0) / oos_std) * math.sqrt(252.0)

        best_is_idx = int(np.argmax(is_sharpes))
        best_oos_sharpe = oos_sharpes[best_is_idx]
        median_oos_sharpe = float(np.median(oos_sharpes))

        if best_oos_sharpe < median_oos_sharpe:
            underperform_count += 1

    pbo = float(underperform_count) / float(len(combos))
    return pbo


# Aliases for compatibility
deflated_sharpe_ratio = compute_dsr
probabilistic_sharpe_ratio = compute_psr
sharpe_haircut = compute_haircut_sharpe
combinatorial_purged_cross_validation = compute_pbo_cscv
expected_maximum_sharpe = compute_expected_max_sharpe


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
    """真实试验自由度账本 (Trial Ledger) — 记录全生命周期搜索空间与有效试验次数 (支持持久化与族内相关性折损)."""

    def __init__(
        self,
        persistent: bool = True,
        repository: Any = None,
        db_path: Optional[Union[str, Path]] = None,
    ):
        """初始化试验账本.

        Args:
            persistent: 是否自动持久化至全局研究数据库 (默认 True)
            repository: 可选注入仓储实例 (依赖倒置)
            db_path: 向后兼容参数 (已由配置中心统一接管)
        """
        self._lock = threading.Lock()
        self._trials_by_family: Dict[str, int] = {}
        self._total_trials: int = 0
        self._records: List[TrialRecord] = []
        self._repo = None

        if persistent and str(db_path) != ":memory:":
            try:
                from alpha_operator_framework.database.repository import AlphaDatabase
                self._repo = repository or AlphaDatabase(db_path=db_path if isinstance(db_path, (str, Path)) else None)
                self._trials_by_family = self._repo.get_trial_counts_by_family()
                self._total_trials = self._repo.get_total_trial_count()
            except Exception as ex:
                logger.debug(f"TrialLedger 仓储初始化跳过或失败: {ex}")

    def record_trial(
        self,
        expression: str,
        family: str = "default",
        region: str = "GBR",
        universe: str = "TOP700",
        metrics: Optional[dict] = None,
    ) -> TrialRecord:
        """记录一次真实试验，累加有效试验自由度并持久化写库."""
        with self._lock:
            self._total_trials += 1
            self._trials_by_family[family] = self._trials_by_family.get(family, 0) + 1
            now_iso = datetime.now().isoformat()
            trial_id = f"TRIAL_{self._total_trials:07d}"

            rec = TrialRecord(
                trial_id=trial_id,
                expression=expression,
                family=family,
                region=region,
                universe=universe,
                created_at=now_iso,
                metrics=metrics or {},
            )
            self._records.append(rec)

            if self._repo is not None:
                try:
                    self._repo.record_trial(
                        trial_id=trial_id,
                        expression=expression,
                        family=family,
                        region=region,
                        universe=universe,
                        metrics=metrics or {},
                        created_at=now_iso,
                    )
                except Exception as ex:
                    logger.warning(f"TrialLedger 持久化写入异常: {ex}")

            return rec

    def get_effective_trials(
        self,
        family: Optional[str] = None,
        intra_family_correlation: float = 0.35,
    ) -> int:
        """获取结构相关性折损后的真实有效试验次数 N_eff = 1 + (N - 1) * (1 - rho)."""
        with self._lock:
            raw_n = self._trials_by_family.get(family, self._total_trials) if family else self._total_trials
            if raw_n <= 1:
                return 1
            # 结构族内相关性折损公式:
            rho = max(0.0, min(0.95, intra_family_correlation))
            n_eff = 1.0 + (raw_n - 1.0) * (1.0 - rho)
            return max(1, int(round(n_eff)))

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
