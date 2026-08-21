"""Alpha筛选与优化模块.

支持两种筛选方式:
  1. 精确指定: alpha_id列表
  2. 条件筛选: sharpe/fitness/turnover等指标范围

本模块不碰网络, 仅提供筛选逻辑和配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Sequence
from pathlib import Path


# ---------------------------------------------------------------------------
# 筛选配置
# ---------------------------------------------------------------------------

@dataclass
class AlphaFilter:
    """Alpha筛选条件配置.

    支持两种模式:
      1. 精确模式: 指定alpha_id列表
      2. 条件模式: 指定指标范围

    两种模式可以组合(先按id筛选,再按条件过滤)。
    """

    # 精确模式: 指定alpha_id列表
    alpha_ids: Optional[List[str]] = None

    # 条件模式: 回测指标范围
    min_sharpe: Optional[float] = None
    max_sharpe: Optional[float] = None

    min_fitness: Optional[float] = None
    max_fitness: Optional[float] = None

    min_turnover: Optional[float] = None
    max_turnover: Optional[float] = None

    min_margin: Optional[float] = None
    max_margin: Optional[float] = None

    min_pnl: Optional[float] = None
    max_pnl: Optional[float] = None

    min_long_count: Optional[int] = None
    min_short_count: Optional[int] = None
    min_long_short_sum: Optional[int] = None

    # 其他条件
    region: Optional[str] = None          # 区域筛选
    dataset_id: Optional[str] = None      # 数据集筛选
    status: Optional[str] = None          # 状态筛选 (IS/OS)

    # 时间范围
    created_after: Optional[str] = None   # 创建时间晚于
    created_before: Optional[str] = None  # 创建时间早于

    # 排序与限制
    order_by: str = "sharpe"              # 排序字段
    descending: bool = True               # 降序
    limit: Optional[int] = None           # 限制数量

    def matches(self, alpha: Dict[str, Any]) -> bool:
        """检查单个alpha是否满足筛选条件.

        Args:
            alpha: alpha结果字典, 包含sharpe/fitness等指标

        Returns:
            是否满足所有条件

        Example:
            >>> filter_config = AlphaFilter(min_sharpe=1.58, min_fitness=1.0)
            >>> alpha = {"sharpe": 1.8, "fitness": 1.2}
            >>> filter_config.matches(alpha)
            True
        """
        # 精确模式: 检查alpha_id
        if self.alpha_ids:
            alpha_id = alpha.get("alpha_id") or alpha.get("id")
            if alpha_id not in self.alpha_ids:
                return False

        # 条件模式: 检查指标范围
        if not self._check_metric(alpha, "sharpe", self.min_sharpe, self.max_sharpe):
            return False

        if not self._check_metric(alpha, "fitness", self.min_fitness, self.max_fitness):
            return False

        if not self._check_metric(alpha, "turnover", self.min_turnover, self.max_turnover):
            return False

        if not self._check_metric(alpha, "margin", self.min_margin, self.max_margin):
            return False

        if not self._check_metric(alpha, "pnl", self.min_pnl, self.max_pnl):
            return False

        # 检查long/short数量
        long_count = alpha.get("longCount") or alpha.get("long_count")
        short_count = alpha.get("shortCount") or alpha.get("short_count")

        if self.min_long_count is not None:
            if not isinstance(long_count, (int, float)) or long_count < self.min_long_count:
                return False

        if self.min_short_count is not None:
            if not isinstance(short_count, (int, float)) or short_count < self.min_short_count:
                return False

        if self.min_long_short_sum is not None:
            total = (long_count or 0) + (short_count or 0)
            if total < self.min_long_short_sum:
                return False

        # 检查region
        if self.region:
            alpha_region = alpha.get("region") or alpha.get("settings", {}).get("region")
            if alpha_region != self.region:
                return False

        # 检查dataset_id
        if self.dataset_id:
            expr = alpha.get("expression") or alpha.get("regular", {}).get("code", "")
            if self.dataset_id not in expr:
                return False

        # 检查status
        if self.status:
            alpha_status = alpha.get("status") or alpha.get("stage")
            if alpha_status != self.status:
                return False

        return True

    def _check_metric(
        self,
        alpha: Dict,
        metric_name: str,
        min_val: Optional[float],
        max_val: Optional[float]
    ) -> bool:
        """检查单个指标是否在范围内."""
        if min_val is None and max_val is None:
            return True

        # 兼容多种字段名
        value = (
            alpha.get(metric_name) or
            alpha.get("is", {}).get(metric_name) or
            alpha.get(f"min_{metric_name}")
        )

        if value is None:
            return False

        if min_val is not None and value < min_val:
            return False

        if max_val is not None and value > max_val:
            return False

        return True


@dataclass
class OptimizeConfig:
    """Alpha优化配置.

    用于指导如何优化选中的alpha。
    """

    # 调整参数
    decay_variants: List[float] = field(default_factory=lambda: [3.0, 6.0, 9.0])
    neutralization_variants: List[str] = field(default_factory=lambda: ["MARKET", "SECTOR", "INDUSTRY"])

    # 窗口调整
    window_variants: List[int] = field(default_factory=lambda: [22, 66, 120, 252])

    # 组合调整
    combine_with_group: bool = True
    group_fields: Optional[List[str]] = None

    # 限制
    max_variants_per_alpha: int = 10


# ---------------------------------------------------------------------------
# 筛选函数
# ---------------------------------------------------------------------------

def filter_alphas(
    alphas: Sequence[Dict[str, Any]],
    filter_config: AlphaFilter
) -> List[Dict[str, Any]]:
    """筛选alpha列表.

    Args:
        alphas: alpha结果列表
        filter_config: 筛选配置

    Returns:
        筛选后的alpha列表(已排序和限制)

    Example:
        >>> alphas = [
        ...     {"alpha_id": "a1", "sharpe": 1.8, "fitness": 1.2},
        ...     {"alpha_id": "a2", "sharpe": 1.5, "fitness": 0.9}
        ... ]
        >>> config = AlphaFilter(min_sharpe=1.58, limit=10)
        >>> filtered = filter_alphas(alphas, config)
        >>> len(filtered)
        1
    """
    # 应用筛选条件
    filtered = [a for a in alphas if filter_config.matches(a)]

    # 排序
    reverse = filter_config.descending
    order_field = filter_config.order_by

    def get_sort_key(alpha):
        val = (
            alpha.get(order_field) or
            alpha.get("is", {}).get(order_field) or
            alpha.get(f"min_{order_field}") or
            0
        )
        return val if isinstance(val, (int, float)) else 0

    filtered.sort(key=get_sort_key, reverse=reverse)

    # 限制数量
    if filter_config.limit and len(filtered) > filter_config.limit:
        filtered = filtered[:filter_config.limit]

    return filtered


def filter_by_ids(
    alphas: Sequence[Dict[str, Any]],
    alpha_ids: List[str]
) -> List[Dict[str, Any]]:
    """按alpha_id列表筛选(便捷函数).

    Args:
        alphas: alpha结果列表
        alpha_ids: alpha_id列表

    Returns:
        匹配的alpha列表

    Example:
        >>> filtered = filter_by_ids(alphas, ["a1", "a2", "a3"])
    """
    config = AlphaFilter(alpha_ids=alpha_ids)
    return filter_alphas(alphas, config)


def filter_by_quality(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.03,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """按质量门筛选(便捷函数).

    Args:
        alphas: alpha结果列表
        min_sharpe: 最小Sharpe
        min_fitness: 最小Fitness
        min_turnover: 最小Turnover
        limit: 限制数量

    Returns:
        筛选后的alpha列表

    Example:
        >>> high_quality = filter_by_quality(
        ...     alphas,
        ...     min_sharpe=1.58,
        ...     min_fitness=1.0,
        ...     min_turnover=0.03
        ... )
    """
    config = AlphaFilter(
        min_sharpe=min_sharpe,
        min_fitness=min_fitness,
        min_turnover=min_turnover,
        limit=limit
    )
    return filter_alphas(alphas, config)


def filter_marginal(
    alphas: Sequence[Dict[str, Any]],
    sharpe_range: tuple = (1.2, 1.8),
    fitness_range: tuple = (0.7, 1.5),
    turnover_range: tuple = (0.01, 0.1),
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选边缘alpha(有优化潜力).

    适合找出:
      - Sharpe在1.2-1.8之间(接近提交线)
      - Fitness在0.7-1.5之间(有提升空间)
      - Turnover适中(不过高不过低)

    Args:
        alphas: alpha结果列表
        sharpe_range: Sharpe范围
        fitness_range: Fitness范围
        turnover_range: Turnover范围
        limit: 限制数量

    Returns:
        边缘alpha列表

    Example:
        >>> marginal = filter_marginal(
        ...     alphas,
        ...     sharpe_range=(1.2, 1.8),
        ...     limit=20
        ... )
    """
    config = AlphaFilter(
        min_sharpe=sharpe_range[0],
        max_sharpe=sharpe_range[1],
        min_fitness=fitness_range[0],
        max_fitness=fitness_range[1],
        min_turnover=turnover_range[0],
        max_turnover=turnover_range[1],
        limit=limit
    )
    return filter_alphas(alphas, config)


def filter_for_submission(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.01,
    max_turnover: float = 0.7,
    min_long_short_sum: int = 100,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选可提交的alpha(便捷函数).

    使用提交质量门:
      - sharpe ≥ 1.58
      - fitness ≥ 1.0
      - 0.01 ≤ turnover ≤ 0.7
      - long + short ≥ 100

    Args:
        alphas: alpha结果列表
        min_sharpe: 最小Sharpe(默认1.58)
        min_fitness: 最小Fitness(默认1.0)
        min_turnover: 最小Turnover(默认0.01)
        max_turnover: 最大Turnover(默认0.7)
        min_long_short_sum: 最小long+short数量(默认100)
        limit: 限制数量

    Returns:
        可提交的alpha列表

    Example:
        >>> ready = filter_for_submission(alphas, limit=50)
    """
    config = AlphaFilter(
        min_sharpe=min_sharpe,
        min_fitness=min_fitness,
        min_turnover=min_turnover,
        max_turnover=max_turnover,
        min_long_short_sum=min_long_short_sum,
        limit=limit
    )
    return filter_alphas(alphas, config)


# ---------------------------------------------------------------------------
# 统计与报告
# ---------------------------------------------------------------------------

def summarize_filtered(
    original: Sequence[Dict[str, Any]],
    filtered: Sequence[Dict[str, Any]],
    filter_config: AlphaFilter
) -> Dict[str, Any]:
    """生成筛选统计报告.

    Args:
        original: 原始alpha列表
        filtered: 筛选后alpha列表
        filter_config: 筛选配置

    Returns:
        统计报告字典

    Example:
        >>> report = summarize_filtered(alphas, filtered, config)
        >>> print(report["pass_rate"])
        0.35
    """
    total = len(original)
    passed = len(filtered)

    # 计算通过率
    pass_rate = passed / total if total > 0 else 0.0

    # 统计指标分布
    def safe_float(val):
        return val if isinstance(val, (int, float)) else 0.0

    metrics = ["sharpe", "fitness", "turnover", "margin"]
    distribution = {}

    for metric in metrics:
        original_vals = [safe_float(a.get(metric) or a.get("is", {}).get(metric)) for a in original]
        filtered_vals = [safe_float(a.get(metric) or a.get("is", {}).get(metric)) for a in filtered]

        distribution[metric] = {
            "original_mean": sum(original_vals) / len(original_vals) if original_vals else 0,
            "original_median": sorted(original_vals)[len(original_vals)//2] if original_vals else 0,
            "filtered_mean": sum(filtered_vals) / len(filtered_vals) if filtered_vals else 0,
            "filtered_median": sorted(filtered_vals)[len(filtered_vals)//2] if filtered_vals else 0,
        }

    return {
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "filter_config": filter_config.__dict__,
        "distribution": distribution,
    }


def filter_alphas_for_optimization(
    alphas: Sequence[Dict[str, Any]],
    alpha_ids: Optional[List[str]] = None,
    min_sharpe: Optional[float] = None,
    max_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    max_fitness: Optional[float] = None,
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选需要优化的 alpha (精确指定 id 或按指标范围).

    Args:
        alphas: alpha 结果列表 (来自 deepen 或平台查询)
        alpha_ids: 指定 alpha_id 列表 (精确模式)
        min_sharpe/max_sharpe/min_fitness/max_fitness/min_turnover/max_turnover: 指标范围
        limit: 限制数量

    Returns:
        筛选后的 alpha 列表
    """
    config = AlphaFilter(
        alpha_ids=alpha_ids,
        min_sharpe=min_sharpe,
        max_sharpe=max_sharpe,
        min_fitness=min_fitness,
        max_fitness=max_fitness,
        min_turnover=min_turnover,
        max_turnover=max_turnover,
        limit=limit,
    )
    return filter_alphas(alphas, config)


def filter_high_quality_alphas(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.03,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选高质量 alpha (便捷函数): sharpe≥1.58, fitness≥1.0, turnover≥0.03."""
    return filter_by_quality(alphas, min_sharpe, min_fitness, min_turnover, limit)


def filter_marginal_alphas(
    alphas: Sequence[Dict[str, Any]],
    sharpe_range: tuple = (1.2, 1.8),
    fitness_range: tuple = (0.7, 1.5),
    turnover_range: tuple = (0.01, 0.1),
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选边缘 alpha (有优化潜力), 便捷函数."""
    return filter_marginal(alphas, sharpe_range, fitness_range, turnover_range, limit)


def filter_ready_for_submission(
    alphas: Sequence[Dict[str, Any]],
    min_sharpe: float = 1.58,
    min_fitness: float = 1.0,
    min_turnover: float = 0.01,
    max_turnover: float = 0.7,
    min_long_short_sum: int = 100,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """筛选可提交的 alpha (便捷函数), 使用提交质量门."""
    return filter_for_submission(
        alphas, min_sharpe, min_fitness, min_turnover, max_turnover, min_long_short_sum, limit
    )


__all__ = [
    "AlphaFilter",
    "OptimizeConfig",
    "filter_alphas",
    "filter_by_ids",
    "filter_by_quality",
    "filter_marginal",
    "filter_for_submission",
    "summarize_filtered",
    "filter_alphas_for_optimization",
    "filter_high_quality_alphas",
    "filter_marginal_alphas",
    "filter_ready_for_submission",
]