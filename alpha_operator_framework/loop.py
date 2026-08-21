"""研究闭环编排 — 把 survey→deepen→submit→distill 串成多轮循环 (P2).

六阶段闭环:
  字段选择 → 表达式合成 → 批量回测 → 信号优化 → 提交 → 沉淀与抽象 ─(回流)─→ 下一轮

本模块负责"环"的编排: 每轮结束时把字段信号统计沉淀写库, 并据此加权采样下一轮字段。
平台回测的实际调用点集中在 ``_run_round_survey`` (依赖 ``run_full_workflow`` / ``alpha_machine``),
接入平台后即可跑通完整闭环; 沉淀与加权采样两部分不依赖网络, 可独立离线测试.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from alpha_operator_framework.distill import (
    aggregate_field_signals,
    weighted_field_sample,
    distill_templates_into_library,
    aggregate_pair_signals,
    aggregate_operator_signals,
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
    min_coverage: float = 0.5          # 字段股票截面覆盖闸
    min_date_coverage: float = 0.9     # 字段历史日期覆盖闸 (平台 dateCoverage; 0=不过滤)
    field_categories: Optional[Tuple[str, ...]] = None  # 字段category白名单 (None=不过滤, 如 ('fundamental',))
    cold_boost: float = 0.5            # 加权采样的冷启动权重
    min_trials: int = 1                # 沉淀时过滤噪声字段的最小回测次数
    execute: bool = False              # 是否真正回测/提交 (默认 dry-run)
    distill: bool = True               # 每轮是否沉淀字段信号
    distill_templates: bool = True     # 每轮是否蒸馏达标表达式回填模板库 (P1)
    distill_pairs: bool = True         # 每轮是否沉淀配对信号 (P2)
    distill_operator_signals: bool = True  # 每轮是否沉淀算子信号 (第5根回流: 6→2 算子挑选)
    max_alpha_budget: int = 1000       # alpha 总量预算 (已回测+本轮回测 <= 此值)
    distill_prune_rules: bool = True   # 每轮是否从 density=0 模板自动生成淘汰规则 (负向蒸馏自生长)
    min_density_for_prune: float = 0.0  # 淘汰规则的密度阈值 (<= 此值生成规则)
    min_prune_sample_n: int = 1        # 淘汰规则的最小回测样本数
    min_template_support: int = 1      # 模板骨架最小支持度
    top_k_templates: Optional[int] = None  # 只回填 support 最高的 top_k 条
    families: tuple = ("unary", "binary", "ternary", "quaternary", "distilled")  # 下一轮消费的模板族
    group_fields: tuple = ("industry", "sector", "subindustry", "market")  # group 槽候选 (GROUP 字段; quaternary/operator 母版依赖)
    seed: Optional[int] = None
    seed_fields: Optional[List[str]] = None  # 首轮字段种子 (None=全量随机采样; 如已提交 alpha 反查字段)
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


def distill_operator_signals_round(
    db,
    *,
    results: List[Dict[str, Any]],
    config: LoopConfig,
    round_n: int,
) -> int:
    """一轮结束后的算子信号沉淀 (第6→2 回流), 不碰网络.

    按算子聚合本轮回测的信号命中率写库 (operator_signal_stats), 供下一轮
    survey 的 select_curated_operators 证据驱动挑选算子 (替代全量展开/随机抽样)。

    Args:
        db: AlphaDatabase 实例
        results: 本轮回测结果行 (含 expression 及 sharpe/fitness 等指标)
        config: 闭环配置
        round_n: 本轮轮次号

    Returns:
        沉淀的算子统计行数
    """
    if not config.distill_operator_signals or not results:
        return 0
    stats = aggregate_operator_signals(
        results,
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        round_n=round_n,
    )
    if not stats:
        return 0
    return db.upsert_operator_signal_stats([s.to_dict() for s in stats], accumulate=True)


def distill_prune_rules_round(
    db,
    *,
    results: List[Dict[str, Any]],
    config: LoopConfig,
    round_n: int,
) -> List[str]:
    """一轮结束后的淘汰规则自生长 (负向蒸馏), 不碰网络.

    从本轮回测结果的密度数据 (compute_density) 里, 把「被回测过但零信号」的模板库
    模板骨架抽象成表达式模式, 写入 template_prune_rules (source='distilled')。
    下一轮 survey 生成表达式时, 规则库匹配过滤这些模式的所有变体 —— 淘汰规则
    随回测经验累积, 越来越精准。

    Args:
        db: AlphaDatabase 实例
        results: 本轮回测结果行 (含 family/template_index/expression_origin 元数据)
        config: 闭环配置
        round_n: 本轮轮次号

    Returns:
        写入的规则 pattern 列表
    """
    if not config.distill_prune_rules or not results:
        return []
    from alpha_operator_framework.domain.density import compute_density
    from alpha_operator_framework.domain import operators
    from alpha_operator_framework.distill.template_pruner import distill_prune_rules_from_density

    density_rows = compute_density(results, access_limited_ops=operators.ACCESS_LIMITED_OPS)
    # compute_density 返回 DensityRow 对象, 转成 dict 供规则蒸馏消费
    density_dicts = [r.to_dict() for r in density_rows]
    return distill_prune_rules_from_density(
        db,
        density_dicts,
        min_density=config.min_density_for_prune,
        min_sample_n=config.min_prune_sample_n,
    )


async def _run_round_survey(config: LoopConfig, round_n: int, field_ids: List[str],
                            database: Optional[Path] = None) -> List[Dict[str, Any]]:
    """执行一轮 字段选择→表达式合成→真实回测, 返回回测结果行.

    只跑 survey 阶段 (不跑 deepen/submit): loop 的核心是「回测→沉淀→加权采样」循环,
    优化(deepen)与提交(submit)是独立的后续层, 不应在每轮闭环里重复消耗回测额度。

    字段来源走本地缓存优先 (aget_datafields), 有缓存的区域零网络请求。

    Args:
        config: 闭环配置
        round_n: 本轮轮次号 (仅用于日志/元数据, 不影响回测)
        field_ids: 本轮字段池 (空=全量采样)
        database: 数据库文件路径; 必须与蒸馏沉淀库一致, 否则 survey 消费的模板
            (template_library) 与 loop 蒸馏回填/淘汰的模板不在同一个库, 回流断裂。

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
            date_coverage=float(r.get("dateCoverage") or 0.0),
            user_count=r.get("userCount", 0),
        )
        for r in field_rows
    ]
    if not specs:
        return []
    # category 白名单: 限定研究范围 (如只跑基本面); None=不过滤
    if config.field_categories:
        def _cat(r: dict) -> str:
            c = r.get("category") or ""
            return str(c.get("id") or "") if isinstance(c, dict) else str(c or "")
        specs = [s for s, r in zip(specs, field_rows) if _cat(r) in config.field_categories]
        if not specs:
            return []

    # 冷启动补位 (非首轮): 加权采样的 planned 只覆盖已试字段, 组合空间耗尽后
    # 闭环会空转 (planned=[] 或全部表达式已回测)。这里用「未试过的冷字段」把
    # 字段池补满到 top_k_fields, 保证全量字段池能持续进场探索。
    if field_ids or round_n > 0:
        planned = list(dict.fromkeys(field_ids))
        if len(planned) < config.top_k_fields:
            tried: set = set()
            try:
                from alpha_operator_framework.database.repository import AlphaDatabase
                _db = AlphaDatabase()
                tried = _db.get_tried_field_ids(config.region)
            except Exception:
                tried = set()
            planned_set = set(planned)
            cold_pool = [s.id for s in specs if s.id not in planned_set and s.id not in tried]
            if cold_pool:
                _rng = random.Random(
                    None if config.seed is None else config.seed + round_n + 1)
                _rng.shuffle(cold_pool)
                planned += cold_pool[: config.top_k_fields - len(planned)]
        field_ids = planned

    survey_config = SurveyConfig(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        # field_ids or None 的语义: 首轮 [] → None 表示「不干预, 全量采样」;
        # 后续轮传加权字段列表+冷字段补位 → 收敛与探索并存。
        field_ids=field_ids or None,
        sample_n=config.top_k_fields,
        backtest_sample_n=config.backtest_sample_n,
        min_coverage=config.min_coverage,
        min_date_coverage=config.min_date_coverage,
        max_alpha_budget=config.max_alpha_budget,
        # template_families 含 distilled: 让本轮 survey 消费上一轮蒸馏出的模板骨架
        template_families=config.families,
        # group_fields: 带 group 槽的模板 (quaternary / operator 母版) 的候选分组维度
        group_fields=list(config.group_fields),
    )

    result = await run_survey_with_fields(specs, survey_config, execute=config.execute,
                                          database=database)
    if not result.success:
        print(f"  ⚠ round {round_n} survey 失败: {result.message}", flush=True)
        return []
    # 回测结果落盘在 results_file (JSON 的 "results" 列表), 从这里取回给 distill 消费;
    # dry-run 时无 results_file → 返回空 (闭环空转但不报错, 仅验证代码路径)。
    if result.results_file and result.results_file.exists():
        payload = json.loads(result.results_file.read_text(encoding="utf-8"))
        return payload.get("results", [])
    print(f"  ⚠ round {round_n} survey 成功但无 results 文件: {result.message}", flush=True)
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
    # 首轮字段: 有种子字段 (如已提交 alpha 反查字段) 用种子起步, 否则全量随机采样。
    # 种子字段已验证有信号, 让字段信号回流从正反馈起点开始, 而不是冷启动随机。
    next_fields: List[str] = list(config.seed_fields or [])
    for r in range(config.rounds):
        # 闭环的核心: next_fields 在轮次间传递 —— 本轮回测 → 沉淀 → 加权采样出的字段,
        # 成为下一轮 _run_round_survey 的输入字段池。首轮 next_fields=[] → 全量采样。
        # 关键: survey 的库必须与蒸馏沉淀库 (db) 一致 —— 否则 survey 消费的模板
        # (template_library) 与 loop 蒸馏回填/淘汰的模板不在同一个库, 回流管道断裂。
        results = await _run_round_survey(config, r, next_fields, database=db.db_path)
        # 四根回流管道同时工作: 字段信号 (6→1) + 模板抽象 (6→2) + 配对信号 (6→2)
        # + 淘汰规则自生长 (6→2, 负向蒸馏: density=0 模板 → 规则库)
        planned = distill_and_plan_next(db, results=results, config=config, round_n=r)
        distilled_templates = distill_templates_round(db, results=results, config=config, round_n=r)
        distilled_pairs = distill_pairs_round(db, results=results, config=config, round_n=r)
        distilled_ops = distill_operator_signals_round(db, results=results, config=config, round_n=r)
        distilled_rules = distill_prune_rules_round(db, results=results, config=config, round_n=r)
        next_fields = planned
        history.append({
            "round": r,
            "planned_next_fields": planned,
            "distilled_stats": len(results),
            "distilled_templates": distilled_templates,
            "distilled_pairs": distilled_pairs,
            "distilled_operator_stats": distilled_ops,
            "distilled_rules": distilled_rules,
        })
    return history
