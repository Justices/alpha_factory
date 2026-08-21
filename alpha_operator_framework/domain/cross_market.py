"""跨市场/跨资产鲁棒性迁移与一致性评估套件 (Cross-Market Robustness & Migration Suite).

功能:
  1. 针对单个 Alpha 表达式，自动化跨多区域 (USA / EUR / CHN / JPN / GBR) 截面数据集进行本地沙盒极速回测
  2. 计算跨市场一致性指数 (Cross-Market Consistency Index, CMCI):
     - 区域夏普离散度 (Sharpe Dispersion)
     - 全球正向收益区域覆盖率 (Positive Regions Ratio)
  3. 智能评定“全天候通用 Alpha” (Universal Alpha)，筛选具备全市场生命力的顶级信号
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from alpha_operator_framework.domain.sandbox.engine import SandboxEngine, SandboxMetrics
from alpha_operator_framework.domain.sandbox.market_data import MarketDataCrossSection


@dataclass
class CrossMarketMetrics:
    """单个区域的回测指标."""

    region: str
    rank_ic: float
    sharpe: float
    turnover: float
    fitness: float


@dataclass
class CrossMarketReport:
    """跨市场鲁棒性综合诊断报告."""

    expression: str
    region_metrics: Dict[str, CrossMarketMetrics]
    mean_sharpe: float
    min_sharpe: float
    max_sharpe: float
    sharpe_dispersion: float         # 夏普离散系数 (标准差 / 均值)
    positive_regions_ratio: float    # 正向超额区域比例 (0.0 ~ 1.0)
    consistency_score: float         # 跨市场一致性指数 CMCI (0.0 ~ 1.0)
    is_universal: bool               # 是否达到全球通用型 Alpha 标准

    @property
    def passed_all_regions(self) -> bool:
        """是否在所有测试区域均获得正夏普."""
        return self.positive_regions_ratio >= 0.99


def evaluate_cross_market_robustness(
    expression: str,
    market_data_dict: Dict[str, MarketDataCrossSection],
    min_universal_sharpe: float = 1.0,
    min_cmci: float = 0.65,
) -> CrossMarketReport:
    """在多个市场区域的数据集上对同一个 Alpha 表达式进行全域鲁棒性评估.

    Args:
        expression: 待评估的 Alpha 表达式
        market_data_dict: 字典 { "USA": md_usa, "EUR": md_eur, "CHN": md_chn, ... }
        min_universal_sharpe: 通用 Alpha 所需的跨市场平均夏普门槛
        min_cmci: 通用 Alpha 所需的一致性指数门槛

    Returns:
        CrossMarketReport 综合报告
    """
    if not market_data_dict:
        raise ValueError("market_data_dict cannot be empty")

    engine = SandboxEngine()
    region_metrics: Dict[str, CrossMarketMetrics] = {}
    sharpe_list: List[float] = []

    for reg, md in market_data_dict.items():
        try:
            m = engine.evaluate(expression, md)
            cm = CrossMarketMetrics(
                region=reg,
                rank_ic=m.rank_ic,
                sharpe=m.sharpe,
                turnover=m.turnover,
                fitness=m.fitness,
            )
        except Exception:
            cm = CrossMarketMetrics(
                region=reg,
                rank_ic=0.0,
                sharpe=-9.9,
                turnover=1.0,
                fitness=0.0,
            )
        region_metrics[reg] = cm
        sharpe_list.append(cm.sharpe)

    # 统计计算
    sharpe_arr = np.array(sharpe_list, dtype=float)
    mean_s = float(np.mean(sharpe_arr))
    min_s = float(np.min(sharpe_arr))
    max_s = float(np.max(sharpe_arr))
    std_s = float(np.std(sharpe_arr))

    # 离散系数 (CV = std / |mean|)
    dispersion = float(std_s / (abs(mean_s) + 1e-4))

    # 正向区域比例 (Sharpe > 0.3)
    pos_count = int(np.sum(sharpe_arr >= 0.3))
    pos_ratio = float(pos_count / len(sharpe_arr))

    # 跨市场一致性指数 CMCI (0.0 ~ 1.0)
    # 结合正向比例与低离散度
    cmci = 0.6 * pos_ratio + 0.4 * max(0.0, min(1.0, 1.0 - dispersion * 0.5))

    is_universal = (
        mean_s >= min_universal_sharpe
        and min_s >= 0.2
        and pos_ratio >= 0.75
        and cmci >= min_cmci
    )

    return CrossMarketReport(
        expression=expression,
        region_metrics=region_metrics,
        mean_sharpe=round(mean_s, 2),
        min_sharpe=round(min_s, 2),
        max_sharpe=round(max_s, 2),
        sharpe_dispersion=round(dispersion, 3),
        positive_regions_ratio=round(pos_ratio, 2),
        consistency_score=round(cmci, 3),
        is_universal=is_universal,
    )
