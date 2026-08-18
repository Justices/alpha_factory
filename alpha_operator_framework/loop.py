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
)


@dataclass
class LoopConfig:
    """研究闭环配置."""

    rounds: int = 1                    # 迭代轮次
    region: str = "EUR"
    universe: str = "TOP2500"
    delay: int = 1
    top_k_fields: int = 80             # 每轮加权采样的字段数
    cold_boost: float = 0.5            # 加权采样的冷启动权重
    min_trials: int = 1                # 沉淀时过滤噪声字段的最小回测次数
    execute: bool = False              # 是否真正回测/提交 (默认 dry-run)
    distill: bool = True               # 每轮是否沉淀字段信号
    distill_templates: bool = True     # 每轮是否蒸馏达标表达式回填模板库 (P1)
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
        db.upsert_field_signal_stats([s.to_dict() for s in stats], accumulate=True)
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


async def _run_round_survey(config: LoopConfig, round_n: int, field_ids: List[str]) -> List[Dict[str, Any]]:
    """执行一轮 字段选择→表达式合成→回测→优化→提交, 返回回测结果行.

    通过 run_full_workflow 串接 survey→deepen→submit:
      - 首轮 field_ids 为空 → 全量字段采样
      - 后续轮 field_ids = 上一轮加权采样结果 → 优先复用有信号的字段
      - template_families 含 distilled → 消费上一轮蒸馏出的模板骨架

    Args:
        config: 闭环配置
        round_n: 本轮轮次号 (仅用于日志/元数据, 不影响回测)
        field_ids: 本轮字段池 (空=全量采样)

    Returns:
        回测结果行列表 (含 expression 及 sharpe/fitness 等指标); 无结果返回 []
    """
    from alpha_operator_framework.ai_workflow import run_full_workflow

    result = await run_full_workflow(
        region=config.region,
        universe=config.universe,
        delay=config.delay,
        field_ids=field_ids or None,
        sample_n=config.top_k_fields,
        template_families=config.families,
        execute=config.execute,
        **config.extra,
    )
    survey = result.get("survey")
    if not survey or not survey.success:
        return []
    if survey.results_file and survey.results_file.exists():
        payload = json.loads(survey.results_file.read_text(encoding="utf-8"))
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
        # 首轮字段选择: 无历史信号时由调用方/平台侧全量采样, 这里留空表示"不干预"
        results = await _run_round_survey(config, r, next_fields)
        planned = distill_and_plan_next(db, results=results, config=config, round_n=r)
        distilled_templates = distill_templates_round(db, results=results, config=config, round_n=r)
        next_fields = planned
        history.append({
            "round": r,
            "planned_next_fields": planned,
            "distilled_stats": len(results),
            "distilled_templates": distilled_templates,
        })
    return history
