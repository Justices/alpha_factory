"""研究闭环编排 — 把 survey→deepen→submit→distill 串成多轮循环 (P2).

六阶段闭环:
  字段选择 → 表达式合成 → 批量回测 → 信号优化 → 提交 → 沉淀与抽象 ─(回流)─→ 下一轮

本模块负责"环"的编排: 每轮结束时把字段信号统计沉淀写库, 并据此加权采样下一轮字段。
平台回测的实际调用点集中在 ``_run_round_survey`` (依赖 ``run_full_workflow`` / ``alpha_machine``),
接入平台后即可跑通完整闭环; 沉淀与加权采样两部分不依赖网络, 可独立离线测试.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from alpha_operator_framework.distill import (
    aggregate_field_signals,
    weighted_field_sample,
    distill_templates_into_library,
    aggregate_pair_signals,
)


@dataclass
class LoopConfig:
    """研究闭环配置."""

    rounds: int = 1                    # 迭代轮次
    region: str = "EUR"
    universe: str = "TOP2500"
    delay: int = 1
    top_k_fields: int = 80             # 每轮加权采样的字段数
    backtest_sample_n: int = 80        # 每轮真实回测的表达式抽样数 (控制额度与耗时, <=0=全部)
    cold_boost: float = 0.5            # 加权采样的冷启动权重
    min_trials: int = 1                # 沉淀时过滤噪声字段的最小回测次数
    execute: bool = False              # 是否真正回测/提交 (默认 dry-run)
    distill: bool = True               # 每轮是否沉淀字段信号
    distill_templates: bool = True     # 每轮是否蒸馏达标表达式回填模板库 (P1)
    distill_pairs: bool = True         # 每轮是否沉淀配对信号 (P2)
    min_template_support: int = 1      # 模板骨架最小支持度
    top_k_templates: Optional[int] = None  # 只回填 support 最高的 top_k 条
    families: tuple = ("unary", "binary", "ternary", "quaternary", "distilled")  # 下一轮消费的模板族
    seed: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)  # 透传 run_full_workflow 的额外参数


def distill_and_plan_next(
    db,
    *,
    results: List[Dict[str, Any]],
    config: LoopConfig,
    round_n: int,
    dataset_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """一轮结束后的沉淀 + 下一轮字段规划 (不碰网络, 可离线测试).

    流程:
      1. aggregate_field_signals: 按字段聚合本轮回测结果的信号统计
      2. upsert_field_signal_stats: 沉淀写库 (accumulate=True 累积多轮经验)
      3. weighted_field_sample: 按 hit_rate 加权采样下一轮字段

    Args:
        db: AlphaDatabase 实例
        results: 本轮回测结果行
        config: 闭环配置
        round_n: 本轮轮次号
        dataset_map: field_id → dataset_id 映射 (可选)

    Returns:
        下一轮加权采样出的 field_id 列表 (供字段选择阶段使用)
    """
    stats = aggregate_field_signals(
        results,
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        round_n=round_n,
        dataset_map=dataset_map,
    )
    if config.distill and stats:
        # accumulate=True 是关键: 多轮研究要「累积」经验而非覆盖 —— 每轮的
        # trials/signal_count 累加, 让 hit_rate 随样本量增大而越来越可信;
        # 若每轮覆盖, 上一轮学到的字段信号就丢了, 闭环退化成一锤子买卖。
        db.upsert_field_signal_stats([s.to_dict() for s in stats], accumulate=True)
    # 加权采样直接基于本轮的 stats (而非读库): 保证「刚回测完的字段」立刻参与
    # 下一轮规划, 无需额外一次数据库查询。跨轮累积的经验已在库中, 由下次查询消费。
    return weighted_field_sample(
        stats,
        sample_n=config.top_k_fields,
        min_trials=config.min_trials,
        cold_boost=config.cold_boost,
        seed=config.seed,
    )


def distill_templates_round(
    db,
    *,
    results: List[Dict[str, Any]],
    config: LoopConfig,
    round_n: int,
) -> int:
    """一轮结束后的模板蒸馏回填 (第6→2 回流), 不碰网络.

    从本轮回测结果里筛出通过信号门的达标表达式, 抽象成模板骨架回填
    template_library (family='distilled'), 供下一轮 survey 消费.

    Args:
        db: AlphaDatabase 实例
        results: 本轮回测结果行 (含 expression 及 sharpe/fitness 等指标)
        config: 闭环配置
        round_n: 本轮轮次号

    Returns:
        回填的模板骨架数
    """
    if not config.distill_templates or not results:
        return 0
    from alpha_operator_framework.domain.density import SignalGate

    # 关键: 只蒸馏「通过信号门」的达标表达式。若把全部回测结果 (含大量噪声)
    # 都抽象成模板回填, 会污染模板库, 让下一轮 survey 花预算去验证无效骨架。
    # 用信号门先过滤, 保证沉淀进库的都是「被验证有信号」的骨架。
    gate = SignalGate()
    expressions = [
        r.get("expression") for r in results
        if gate.is_signal(r)[0] and (r.get("expression") or "").strip()
    ]
    if not expressions:
        return 0
    return distill_templates_into_library(
        db,
        expressions,
        round_n=round_n,
        min_support=config.min_template_support,
        top_k=config.top_k_templates,
    )


def distill_pairs_round(
    db,
    *,
    results: List[Dict[str, Any]],
    config: LoopConfig,
    round_n: int,
) -> int:
    """一轮结束后的配对信号沉淀 (第6→2 回流), 不碰网络.

    从回测结果里筛出带 pair_spec 元数据的配对结果, 聚合信号命中率写库
    (pair_signal_stats), 供下一轮优先复用「被验证有信号」的配对。

    Args:
        db: AlphaDatabase 实例
        results: 本轮回测结果行 (配对任务含 pair_spec/pair_kind 元数据)
        config: 闭环配置
        round_n: 本轮轮次号

    Returns:
        沉淀的配对数
    """
    if not config.distill_pairs or not results:
        return 0
    stats = aggregate_pair_signals(
        results,
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        round_n=round_n,
    )
    if not stats:
        return 0
    return db.upsert_pair_signal_stats([s.to_dict() for s in stats], accumulate=True)


async def _run_round_survey(config: LoopConfig, round_n: int, field_ids: List[str]) -> List[Dict[str, Any]]:
    """执行一轮 字段选择→表达式合成→真实回测, 返回回测结果行.

    只跑 survey 阶段 (不跑 deepen/submit): loop 的核心是「回测→沉淀→加权采样」循环,
    优化(deepen)与提交(submit)是独立的后续层, 不应在每轮闭环里重复消耗回测额度。

    字段来源走本地缓存优先 (aget_datafields), 有缓存的区域零网络请求。

    Args:
        config: 闭环配置
        round_n: 本轮轮次号 (仅用于日志/元数据, 不影响回测)
        field_ids: 本轮字段池 (空=全量采样)

    Returns:
        回测结果行列表 (含 expression 及 sharpe/fitness 等指标); 无结果返回 []
    """
    from alpha_operator_framework.ai_workflow import run_survey_with_fields, SurveyConfig
    from alpha_operator_framework.cache.datafields import aget_datafields
    from alpha_operator_framework.domain import fields as _fields

    # 本地缓存优先加载字段 (避免全量实时拉取 data-fields 触发 429)
    field_rows = await aget_datafields(config.region, config.universe, config.delay)
    specs = [
        _fields.FieldSpec(
            id=r["id"],
            dataset_id=r.get("dataset", {}).get("id", ""),
            type=r.get("type", "MATRIX"),
            coverage=r.get("coverage", 0.0),
            user_count=r.get("userCount", 0),
        )
        for r in field_rows
    ]
    if not specs:
        return []

    survey_config = SurveyConfig(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        # field_ids or None 的语义: 首轮 [] → None 表示「不干预, 全量采样」;
        # 后续轮传加权字段列表 → 优先复用上一轮有信号的字段, 收敛搜索空间。
        field_ids=field_ids or None,
        sample_n=config.top_k_fields,
        backtest_sample_n=config.backtest_sample_n,
        # template_families 含 distilled: 让本轮 survey 消费上一轮蒸馏出的模板骨架
        template_families=config.families,
    )

    result = await run_survey_with_fields(specs, survey_config, execute=config.execute)
    if not result.success:
        return []
    # 回测结果落盘在 results_file (JSON 的 "results" 列表), 从这里取回给 distill 消费;
    # dry-run 时无 results_file → 返回空 (闭环空转但不报错, 仅验证代码路径)。
    if result.results_file and result.results_file.exists():
        payload = json.loads(result.results_file.read_text(encoding="utf-8"))
        return payload.get("results", [])
    return []


async def run_research_loop(db, config: LoopConfig) -> List[Dict[str, Any]]:
    """多轮研究闭环主入口.

    Args:
        db: AlphaDatabase 实例 (沉淀写库)
        config: 闭环配置

    Returns:
        每轮的规划结果 (字段清单 + 沉淀统计摘要)
    """
    history: List[Dict[str, Any]] = []
    next_fields: List[str] = []
    for r in range(config.rounds):
        # 闭环的核心: next_fields 在轮次间传递 —— 本轮回测 → 沉淀 → 加权采样出的字段,
        # 成为下一轮 _run_round_survey 的输入字段池。首轮 next_fields=[] → 全量采样。
        results = await _run_round_survey(config, r, next_fields)
        # 三根回流管道同时工作: 字段信号 (第6→1) + 模板抽象 (第6→2) + 配对信号 (第6→2)
        planned = distill_and_plan_next(db, results=results, config=config, round_n=r)
        distilled_templates = distill_templates_round(db, results=results, config=config, round_n=r)
        distilled_pairs = distill_pairs_round(db, results=results, config=config, round_n=r)
        next_fields = planned
        history.append({
            "round": r,
            "planned_next_fields": planned,
            "distilled_stats": len(results),
            "distilled_templates": distilled_templates,
            "distilled_pairs": distilled_pairs,
        })
    return history
