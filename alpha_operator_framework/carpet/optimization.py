"""Pruning and signal-optimization stages for carpet mining."""

from __future__ import annotations

import logging
from typing import List

from alpha_operator_framework.distill.diagnostic import FailureMode, diagnose_alpha_failure
from alpha_operator_framework.distill.mutation import AlphaMutator
from alpha_operator_framework.domain.families import Task
from alpha_operator_framework.domain.judge.evaluator import AlphaJudge
from alpha_operator_framework.platform.platform_simulator import PlatformAlphaResult
from alpha_operator_framework.research.db_persister import persist_research_pipeline_results

logger = logging.getLogger(__name__)


def prune_zero_signal_families(
    miner,
    cohort: List[Task],
    results: List[PlatformAlphaResult],
) -> List[str]:
    """【二维解耦智能剪枝】: 结合多字段共识与金牌豁免机制，淘汰真正失效的结构模式 (杜绝误杀与漏判)."""
    from alpha_operator_framework.distill.template_pruner import (
        evaluate_and_prune_templates_2d,
        analyze_field_signal_quality,
    )

    # 1. 执行二维多字段共识剪枝
    prune_res = evaluate_and_prune_templates_2d(
        db=miner.db,
        results=results,
        min_distinct_fields=2,
        failure_rate_threshold=0.80,
        max_avg_sharpe=0.10,
        min_sample_n=3,
    )

    for log in prune_res.audit_logs:
        logger.info(log)

    # 2. 评估字段级信号画像 (噪声字段 vs Alpha 字段)
    field_profiles = analyze_field_signal_quality(results)
    noise_fields = [f for f, p in field_profiles.items() if p.is_noise]
    alpha_fields = [f for f, p in field_profiles.items() if p.tier == "Alpha"]
    if noise_fields:
        logger.info(f"⚠️ [字段画像] 识别到 {len(noise_fields)} 个跨族纯白噪声字段 (暂不误杀对应模板): {noise_fields}")
    if alpha_fields:
        logger.info(f"✨ [字段画像] 识别到 {len(alpha_fields)} 个高信噪比 Alpha 特征: {alpha_fields}")

    return prune_res.pruned_patterns

def optimize_positive_signals(
    miner,
    results: List[PlatformAlphaResult],
) -> List[PlatformAlphaResult]:
    """针对产生正向潜力的 Alpha 自动执行 AST 变异优化与二次实测."""
    if not miner.config.optimize_signals or not miner.config.execute:
        return []

    candidates_to_opt = [
        r for r in results
        if r.is_valid and (r.sharpe >= miner.config.min_sharpe_for_opt or r.annualized_return >= miner.config.min_return_for_opt)
    ]

    if not candidates_to_opt:
        logger.info("未发现达到自优化门槛的正向 Alpha，跳过二代变异")
        return []

    print(f"\n🧬 发现 {len(candidates_to_opt)} 个正向 Alpha，开始触发针对性 AST 基因突变与自优化...")

    mutation_tasks: List[Task] = []
    for parent in candidates_to_opt:
        # 1. 诊断病因
        diag = diagnose_alpha_failure({
            "sharpe": parent.sharpe,
            "fitness": parent.fitness,
            "turnover": parent.turnover,
            "returns": parent.annualized_return,
            "drawdown": parent.max_drawdown,
        })

        # 2. 针对高换手率突变
        if parent.turnover > 0.70:
            mutated_exprs = AlphaMutator.mutate_expression(parent.expression, FailureMode.HIGH_TURNOVER)
            for m_idx, m_expr in enumerate(mutated_exprs[:2]):
                mutation_tasks.append(
                    Task(
                        family="optimized_smooth",
                        template_index=100 + m_idx,
                        fields_per_alpha=1,
                        expression=m_expr,
                        decay=20,  # 提升 decay 周期压降换手率
                        meta={"parent_alpha_id": parent.alpha_id, "opt_type": "turnover_compression"},
                    )
                )

        # 3. 针对边际 Sharpe 提纯
        if 0.3 <= parent.sharpe < 1.25:
            mutated_exprs = AlphaMutator.mutate_expression(parent.expression, FailureMode.MARGINAL_SHARPE)
            for m_idx, m_expr in enumerate(mutated_exprs[:2]):
                mutation_tasks.append(
                    Task(
                        family="optimized_sharpe",
                        template_index=200 + m_idx,
                        fields_per_alpha=1,
                        expression=m_expr,
                        decay=parent.raw_details.get("settings", {}).get("decay", miner.config.decay),
                        meta={"parent_alpha_id": parent.alpha_id, "opt_type": "sharpe_enhancement"},
                    )
                )

    if not mutation_tasks:
        return []

    print(f"🚀 正在提交 {len(mutation_tasks)} 个二代变异优化任务到 BRAIN 平台...")
    opt_results = miner.simulator.simulate_batch(
        tasks=mutation_tasks,
        settings={
            "region": miner.config.region,
            "universe": miner.config.universe,
            "delay": miner.config.delay,
            "decay": miner.config.decay,
            "neutralization": miner.config.neutralization,
            "truncation": miner.config.truncation,
        },
        poll_interval=4.0,
        timeout=300.0,
    )

    # 实时落库二代优化因子
    valid_details = [r.raw_details for r in opt_results if r.raw_details]
    judge = AlphaJudge()
    reports = judge.rank_candidates(valid_details) if valid_details else []
    ranked_cands = [
        {
            "alpha_id": rep.alpha_id,
            "expression": rep.expression,
            "verdict": rep.verdict.value,
            "priority_score": rep.priority_score,
            "metrics": rep.metrics,
            "recommendation": rep.actionable_recommendations[0] if rep.actionable_recommendations else "",
        }
        for rep in reports
    ]

    persist_research_pipeline_results(
        db=miner.db,
        paper_title=f"GBR Signal Optimization ({','.join(miner.config.datasets)})",
        tasks=mutation_tasks,
        settings={"region": miner.config.region, "universe": miner.config.universe, "delay": miner.config.delay},
        platform_results=opt_results,
        ranked_candidates=ranked_cands,
        source_type="evolution",
    )

    return opt_results



__all__ = ["prune_zero_signal_families", "optimize_positive_signals"]
