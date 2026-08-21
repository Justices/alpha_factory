"""金融经济学假说分类体系与知识库 (Hypothesis Taxonomy & Catalog).

定义基于金融经济学逻辑的假说体系，摒弃盲目排列组合。
涵盖五大核心 Alpha 来源:
  1. MOMENTUM_REVERSAL: 时序动量、横截面动量、高阶导数与极值反转
  2. ANALYST_DISPERSION: 卖方分析师预期修正分歧度、目标价差价与超预期漂移
  3. LIQUIDITY_VOLATILITY: Amihud 非流动性溢价、量价背离与异常波动率冲击
  4. QUALITY_VALUE: 盈利质量持续性 (Sloan Accruals)、资本结构与估值错配
  5. SENTIMENT_ATTENTION: 散户关注度膨胀与机构真实资金流背离
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Sequence, Tuple


class HypothesisCategory(str, Enum):
    """金融假说类别枚举."""

    MOMENTUM_REVERSAL = "momentum_reversal"
    ANALYST_DISPERSION = "analyst_dispersion"
    LIQUIDITY_VOLATILITY = "liquidity_volatility"
    QUALITY_VALUE = "quality_value"
    SENTIMENT_ATTENTION = "sentiment_attention"


@dataclass(frozen=True)
class EconomicHypothesis:
    """单个量化经济学假说定义."""

    id: str
    name: str
    category: HypothesisCategory
    premise: str          # 金融前提假设
    rationale: str        # 为什么能产生 Alpha (超额收益机理)
    required_slots: Tuple[str, ...]    # 槽位需求 (如 "analyst_metric", "normalizer")
    templates: Tuple[str, ...]         # 对应的结构正交 AST 表达式模板


BUILTIN_HYPOTHESES: Tuple[EconomicHypothesis, ...] = (
    # 1. 分析师预期修正与分歧假说
    EconomicHypothesis(
        id="hyp_analyst_revision_momentum",
        name="分析师一致预期上调加速动量",
        category=HypothesisCategory.ANALYST_DISPERSION,
        premise="分析师群体存在信息反应不足与羊群效应 (PEAD 盈余公告后漂移).",
        rationale="近期上调次数净值占比加速增长的标的，未来 1-3 个月存在持续超额回报.",
        required_slots=("analyst_revision", "normalizer"),
        templates=(
            "ts_decay_linear(rank({a}) / rank({b}), 10)",
            "ts_delta(rank({a}), 22) - ts_delta(rank({b}), 22)",
            "group_neutralize(ts_rank({a} / {b}, 22), industry)",
        ),
    ),
    # 2. 量价背离与流动性冲击假说
    EconomicHypothesis(
        id="hyp_volume_price_divergence",
        name="量价背离与机构隐蔽吸筹",
        category=HypothesisCategory.LIQUIDITY_VOLATILITY,
        premise="缩量微涨或放量滞涨通常代表筹码转移与流动性吸收.",
        rationale="价格微弱上行伴随成交量萎缩，代表卖压耗尽，后续大概率向上突破.",
        required_slots=("price_field", "volume_field"),
        templates=(
            "ts_rank({a}, 10) - ts_rank({b}, 10)",
            "group_neutralize(ts_delta({a}, 5) / (ts_mean({b}, 20) + 1e-4), subindustry)",
            "ts_regression(ts_zscore({a}, 60), ts_zscore({b}, 60), 60, rettype=2)",
        ),
    ),
    # 3. 盈利质量与应计项背离假说
    EconomicHypothesis(
        id="hyp_accruals_quality_anomaly",
        name="盈利质量与应计项背离 (Sloan Anomaly)",
        category=HypothesisCategory.QUALITY_VALUE,
        premise="会计利润中应计利润 (Accruals) 占比过高往往掩盖真实的经营现金流恶化.",
        rationale="经营现金流强劲且低应计项的企业，盈余质量高，具备长期超额收益.",
        required_slots=("cashflow_field", "earnings_field"),
        templates=(
            "rank({a}) - rank({b})",
            "group_neutralize(rank({a} / ({b} + 1e-4)), sector)",
            "ts_rank({a}, 252) / (ts_rank({b}, 252) + 0.01)",
        ),
    ),
    # 4. 极端放量反转假说
    EconomicHypothesis(
        id="hyp_extreme_reversal_panic",
        name="短期恐慌极值放量反转",
        category=HypothesisCategory.MOMENTUM_REVERSAL,
        premise="散户恐慌盘踩踏抛售导致短期价格过度反应 (Overreaction).",
        rationale="短期极端下跌伴随成交量巨幅放大，次日存在高胜率均值回归反弹.",
        required_slots=("price_return", "volatility_field"),
        templates=(
            "-1.0 * ts_zscore({a}, 5) * ts_rank({b}, 5)",
            "ts_rank(ts_arg_min({a}, 10), 10) * group_rank({b}, industry)",
        ),
    ),
    # 5. 情绪与关注度背离假说
    EconomicHypothesis(
        id="hyp_sentiment_attention_divergence",
        name="情绪过度狂热顶峰做空",
        category=HypothesisCategory.SENTIMENT_ATTENTION,
        premise="社交媒体关注度与情绪指标达到历史 99 分位数时，通常为噪音交易者顶部接盘.",
        rationale="极高情绪伴随动量放缓预示动量衰竭，做空获利.",
        required_slots=("sentiment_field", "attention_field"),
        templates=(
            "-1.0 * ts_decay_linear(rank({a}) * rank({b}), 5)",
            "group_neutralize(ts_rank({a}, 66) - ts_rank({b}, 66), market)",
        ),
    ),
)
